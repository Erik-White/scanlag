from typing import Any, Optional, Iterable, Dict, List, Tuple
from math import e, exp, log, log10, sqrt
from datetime import timedelta


class GrowthCurve:
    """
    An abstract class to provide growth curve fitting and parameters
    """
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        cls.__growth_rate = None
        cls.__carrying_capacity = None
        cls.__lag_time = None

    @property
    def carrying_capacity(self) -> float:
        """
        The maximal population size, A

        Defined as the asymtote approached by the maximal growth measurement

        :returns: the maximal colony area, in units of log2[area]
        """
        if self.__carrying_capacity is None:
            self.fit_growth_curve()

        return self.__carrying_capacity

    @property
    def doubling_time(self) -> timedelta:
        """
        The doubling time at the maximal growth rate

        Defined as ln2 / μmax

        :returns: the minimum time taken for a colony to double in size as a timedelta
        """
        doubling = 0

        if self.growth_rate > 0:
            doubling = log(2) / self.growth_rate

        return timedelta(seconds = doubling)

    @property
    def growth_curve_data(self) -> Dict[timedelta, float]:
        """
        A set of growth measurements over time

        :returns: a dictionary of measurements at time intervals
        """
        raise NotImplementedError("This property must be implemented in a derived class")

    @property
    def growth_rate(self) -> float:
        """
        The maximum specific growth rate, μmax

        Defined as the tangent in the inflection point of the growth curve

        :returns: the maximal growth rate in units of log2[area] / second
        """
        if self.__growth_rate is None:
            self.fit_growth_curve()

        return self.__growth_rate

    @property
    def lag_time(self) -> timedelta:
        """
        The lag time, λ

        Defined as the x-axis intercept of the maximal growth rate (μmax)

        :returns: the lag phase of growth as a timedelta
        """
        if self.__lag_time is None:
            self.fit_growth_curve()

        if self.__lag_time.total_seconds() < 0:
            return timedelta(seconds = 0)
        else:
            return self.__lag_time

    def fit_growth_curve(self, growth_model: callable = None, initial_params: List[float] = None):
        """
        Fit a parametrized version of the Gompertz function to data

        Ref: Modeling of the Bacterial Growth Curve, Zwietering et al 1990

        :param growth_model: optionally specify a different growth model
        :param initial_params: initial estimate of parameters for the growth model
        """
        from numpy import isinf, sqrt, diag

        if growth_model is None:
            growth_model = self.gompertz

        timestamps = [timestamp.total_seconds() for timestamp in sorted(self.growth_curve_data.keys())]
        measurements = [val for _, val in sorted(self.growth_curve_data.items())]

        carrying_capacity = 0
        growth_rate = 0
        lag_time = 0

        if len(timestamps) > 0 and len(measurements) > 0:
            if initial_params is None:
                lag_time, growth_rate, carrying_capacity = GrowthCurve.estimate_parameters(timestamps, measurements)
                initial_params = [min(measurements), lag_time, growth_rate * 3600, carrying_capacity]

            results = self.__fit_curve(
                growth_model,
                timestamps,
                measurements,
                initial_params = initial_params
            )

            if results is not None:
                (_, lag_time, growth_rate, carrying_capacity), conf = results

                # Calculate standard deviation if results provided
                if not (isinf(conf)).all():
                    conf = sqrt(diag(conf.clip(min = 0)))
                else:
                    conf = None

        self.__lag_time = timedelta(seconds = lag_time)
        self.__growth_rate = growth_rate / 3600
        self.__carrying_capacity = carrying_capacity

    @staticmethod
    def estimate_parameters(timestamps: Iterable[float], measurements: Iterable[float], window: int = 10) -> Tuple[float]:
        """
        Estimate the initial parameters for curve fitting

        Lag time:
            Approximates the inflection point in the growth curve as the timestamp where the
            difference in measurements is greater than the mean difference between all measurements,
            plus the standard deviation.

            If the growth rate can be found with linear regression, the intercept of the slope of
            the maximum specific growth rate with the time is taken instead

        Growth rate:
            Approximates the maximum specific growth rate as maximum growth rate measured over a
            sliding window, after the lag time

        Carrying capacity:
            Approximates the asymptote approached by the growth curve as the maximal measurement plus
            the standard deviation of the differences between measurements

        :param timestamps: a collections of time values as floats
        :param measurements: a collection of growth measurements corresponding to timestamps
        :param window: the window size used for finding the maximum growth rate
        :returns: estimation of lag time, growth rate and carrying capacity
        """
        from numpy import diff
        from scipy.stats import linregress

        if not len(timestamps) > 0 or not len(measurements) > 0 or len(timestamps) < window:
            return 0, 0, 0

        if len(timestamps) != len(measurements):
            raise ValueError(
                f"The timestamps ({len(timestamps)} elements) and measurements"
                f" ({len(measurements)} elements) must contain the same number of elements,"
                f" and contain at least as many elements as the window size ({window})"
            )

        diffs = diff(measurements)

        # Carrying capacity
        carrying_capacity = max(measurements) + diffs.std()

        # Lag time and growth rate
        inflection = list(diffs).index(diffs[diffs > diffs.mean() + diffs.std()][0])
        slopes = list()
        for i in range(inflection, len(timestamps) - window):
            # Find the slope at the exponential growth phase over a sliding window
            slope, intercept, *__ = linregress(timestamps[i: i + window], measurements[i: i + window])
            slopes.append((slope, intercept))

        if len(slopes) > 0:
            growth_rate, intercept = max(slopes)
            lag_time = -intercept / growth_rate
        else:
            lag_time = timestamps[inflection // 2]
            growth_rate = max(diffs)

        return lag_time, growth_rate, carrying_capacity

    @staticmethod
    def gompertz(
        elapsed_time: float,
        initial_size: float,
        lag_time: float,
        growth_rate: float,
        carrying_capacity: float
    ) -> float:
        """
        Parametrized version of the Gompertz function

        From Herricks et al, 2016 doi: 10.1534/g3.116.037044

        :param elapsed_time: time since start
        :param initial_size: initial growth measurement
        :param growth_rate: the maximum specific growth rate, μmax
        :param lag_time: the time at the inflection point in the growth curve
        :param carrying_capacity: the maximal population size, A
        :returns: a value for the colony area at elapsed_time, in units of log2[area]
        """
        from scipy.special import logsumexp

        try:
            return (
                initial_size + carrying_capacity * exp(
                    # scipy.special.logsumexp is used to minimise overflow errors
                    -logsumexp((
                        ((growth_rate * e) / carrying_capacity) * (lag_time - elapsed_time)
                    ) + log10((3 + sqrt(5)) / 2))
                )
            )
        except (OverflowError, ZeroDivisionError):
            return 0

    @staticmethod
    def __fit_curve(
        curve_function: callable,
        timestamps: List[float],
        measurements: List[float],
        initial_params: List[float] = None,
        **kwargs
    ) -> Optional[Tuple[Any]]:
        """
        Uses non-linear least squares to fit a function to data

        timestamps and measurements should be the same length

        :param curve_function: a function to fit to data
        :param timestamps: a list of observation timestamps
        :param measurements: a list of growth observations
        :param initial_params: initial estimate for the parameters of curve_function
        :param kwargs: arguments to pass to scipy.optimize.curve_fit
        :returns: a tuple containing optimal result parameters, or None if no fit could be made
        """
        import warnings
        from scipy.optimize import curve_fit, OptimizeWarning

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", OptimizeWarning)
                return curve_fit(curve_function, timestamps, measurements, p0 = initial_params, **kwargs)
        except RuntimeError:
            return None