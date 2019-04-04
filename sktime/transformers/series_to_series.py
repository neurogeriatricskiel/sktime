from sklearn.utils.validation import check_is_fitted
from sklearn.utils.validation import check_random_state
import numpy as np
import pandas as pd
from ..utils.validation import check_equal_index
from ..utils.transformations import tabularize, concat_nested_arrays
from .base import BaseTransformer

__all__ = ['RandomIntervalSegmenter']


class RandomIntervalSegmenter(BaseTransformer):
    """Transformer that segments time-series into random intervals with random starting points and lengths. Some
    intervals may overlap and may be duplicates.

    Parameters
    ----------
    n_intervals : str, int or float
        Number of intervals to generate.
        - If "sqrt", sqrt of m is used where m is length of time series.
        - If "random", random number of intervals is generated.
        - If int, n_intervals intervals are generated.
        - If float, n_intervals * m is used with n_intervals giving the fraction of intervals of the time series length.
        Default is "sqrt".

    random_state : int, RandomState instance or None, optional (default=None)
        If int, random_state is the seed used by the random number generator;
        If RandomState instance, random_state is the random number generator;
        If None, the random number generator is the RandomState instance used
        by `np.random`.

    check_input : bool, optional (default=True)
        When set to ``True``, inputs will be validated, otherwise inputs are assumed to be valid
        and no checks are performed. Use with caution.
    """

    def __init__(self, n_intervals='sqrt', min_length=None, random_state=None, check_input=True):

        self.input_indexes_ = []  # list of time-series indexes of each column
        self.check_input = check_input
        self.intervals_ = []
        self.input_shape_ = ()
        self.columns_ = []
        self.min_length = 1 if min_length is None else min_length
        self.n_intervals = n_intervals
        self.random_state = random_state

    @property
    def random_state(self):
        return self._random_state

    @random_state.setter
    def random_state(self, random_state):
        """Set random state and update rng"""
        self._random_state = random_state
        self._rng = check_random_state(random_state)

    def fit(self, X, y=None):
        """Fit transformer, generating random interval indices.

        Parameters
        ----------
        X : pandas DataFrame of shape [n_samples, n_features]
            Input data
        y : pandas Series, shape (n_samples, ...), optional
            Targets for supervised learning.

        Returns
        -------
        self : RandomIntervalSegmenter
            This estimator
        """
        if self.check_input:
            # TODO check input is series column, not column of primitives
            pass

        self.input_shape_ = X.shape

        # Retrieve time-series indexes from each column.
        # TODO generalise to columns with series of unequal length
        self.input_indexes_ = [X.iloc[0, c].index if hasattr(X.iloc[0, c], 'index')
                               else np.arange(X.iloc[0, c].shape[0]) for c in range(self.input_shape_[1])]

        # Compute random intervals for each column.
        # TODO if multiple columns are passed, introduce option to compute one set of shared intervals,
        #  or rely on ColumnTransformer?
        if self.n_intervals == 'random':
            self.intervals_ = [self._rand_intervals_rand_n(self.input_indexes_[c])
                               for c in range(self.input_shape_[1])]
        else:
            self.intervals_ = [self._rand_intervals_fixed_n(self.input_indexes_[c], n=self.n_intervals)
                               for c in range(self.input_shape_[1])]
        return self

    def transform(self, X, y=None):
        """Transform X, segments time-series in each column into random intervals using interval indices generated
        during `fit`.

        Parameters
        ----------
        X : nested pandas DataFrame of shape [n_samples, n_features]
            Nested dataframe with time-series in cells.

        Returns
        -------
        Xt : pandas DataFrame
          Transformed pandas DataFrame with same number of rows and one column for each generated interval.
        """

        # Check is fit had been called
        check_is_fitted(self, 'intervals_')

        # Check inputs.
        if self.check_input:
            # Check that the input is of the same shape as the one passed
            # during fit.
            if (X.shape[1] if X.ndim == 2 else 1) != self.input_shape_[1]:
                raise ValueError('Number of columns of input is different from what was seen'
                                 'in `fit`')
            # Input validation
            if not all([np.array_equal(fit_idx, trans_idx) for trans_idx, fit_idx in zip(check_equal_index(X),
                                                                                         self.input_indexes_)]):
                raise ValueError('Indexes of input time-series are different from what was seen in `fit`')

        # Segment into intervals.
        intervals = []
        self.columns_ = []
        for c, (colname, col) in enumerate(X.items()):
            # Tabularize each column assuming series have equal indexes in any given column.
            # TODO generalise to non-equal-index cases
            arr = tabularize(col, return_array=True)
            for start, end in self.intervals_[c]:
                interval = arr[:, start:end]
                intervals.append(interval)
                self.columns_.append(f'{colname}_{start}_{end}')

        # Return nested pandas DataFrame.
        Xt = pd.DataFrame(concat_nested_arrays(intervals, return_arrays=True))
        Xt.columns = self.columns_
        return Xt

    def _rand_intervals_rand_n(self, x):
        """Compute a random number of intervals from index (x) with
        random starting points and lengths. Intervals are unique, but may overlap.

        Parameters
        ----------
        x : array_like, shape = [n_observations]
        random_state : int, RandomState instance or None, optional (default=None)

        Returns
        -------
        intervals : array-like, shape = [n, 2]
            2d array containing start and end points of intervals

        References
        ----------
        [1] Deng, Houtao, et al. "A time series forest for classification and feature extraction."
        Information Sciences 239 (2013): 142-153.
        """

        starts = []
        ends = []
        m = x.shape[0]  # series length
        W = self._rng.randint(1, m, size=int(np.sqrt(m)))
        for w in W:
            size = m - w + 1
            start = self._rng.randint(size, size=int(np.sqrt(size)))
            starts.extend(start)
            for s in start:
                end = s + w
                ends.append(end)
        return np.column_stack([starts, ends])

    def _rand_intervals_fixed_n(self, x, n):
        """Compute a fixed number (n) of intervals from index (x) with
        random starting points and lengths. Intervals may overlap and may not be unique.

        Parameters
        ----------
        x : array_like, shape = [n_observations]
            Array containing the time-series index.
        n : 'sqrt', 'log', float or int
        random_state : int, RandomState instance or None, optional (default=None)

        Returns
        -------
        intervals : array-like, shape = [n, 2]
            2d array containing start and end points of intervals
        """

        m = len(x)
        # compute number of random intervals relative to series length (m)
        if np.issubdtype(type(n), np.integer) and (n >= 1):
            pass
        elif n == 'sqrt':
            n = int(np.sqrt(m))
        elif n == 'log':
            n = int(np.log(m))
        elif np.issubdtype(type(n), np.floating) and (n > 0) and (n <= 1):
            n = int(m * n)
        else:
            raise ValueError(f'Number of intervals must be either "random", "sqrt", a positive integer, or a float '
                             f'value between 0 and 1, but found {n}.')

        # make sure there is at least one interval
        n = np.maximum(1, n)

        starts = self._rng.randint(m - self.min_length + 1, size=n)
        if n == 1:
            starts = [starts]  # make it an iterable

        ends = [start + self._rng.randint(self.min_length, m - start + 1) for start in starts]
        return np.column_stack([starts, ends])
