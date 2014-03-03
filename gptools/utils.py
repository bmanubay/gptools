# Copyright 2013 Mark Chilenski
# This program is distributed under the terms of the GNU General Purpose License (GPL).
# Refer to http://www.gnu.org/licenses/gpl.txt
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Provides convenient utilities for working with the classes and results from :py:mod:`gptools`.
"""

from __future__ import division

import collections
import warnings
import scipy
import scipy.optimize
import scipy.special
import scipy.stats
import matplotlib.pyplot as plt
import matplotlib.widgets as mplw
import matplotlib.gridspec as mplgs


def wrap_fmin_slsqp(fun, guess, opt_kwargs={}):
    """Wrapper for :py:func:`fmin_slsqp` to allow it to be called with :py:func:`minimize`-like syntax.

    This is included to enable the code to run with :py:mod:`scipy` versions
    older than 0.11.0.

    Accepts `opt_kwargs` in the same format as used by
    :py:func:`scipy.optimize.minimize`, with the additional precondition
    that the keyword `method` has already been removed by the calling code.

    Parameters
    ----------
    fun : callable
        The function to minimize.
    guess : sequence
        The initial guess for the parameters.
    opt_kwargs : dict, optional
        Dictionary of extra keywords to pass to
        :py:func:`scipy.optimize.minimize`. Refer to that function's
        docstring for valid options. The keywords 'jac', 'hess' and 'hessp'
        are ignored. Note that if you were planning to use `jac` = True
        (i.e., optimization function returns Jacobian) and have set
        `args` = (True,) to tell :py:meth:`update_hyperparameters` to
        compute and return the Jacobian this may cause unexpected behavior.
        Default is: {}.

    Returns
    -------
    Result : namedtuple
        :py:class:`namedtuple` that mimics the fields of the
        :py:class:`Result` object returned by
        :py:func:`scipy.optimize.minimize`. Has the following fields:

        ======= ======= ===================================================================================
        status  int     Code indicating the exit mode of the optimizer (`imode` from :py:func:`fmin_slsqp`)
        success bool    Boolean indicating whether or not the optimizer thinks a minimum was found.
        fun     float   Value of the optimized function (-1*LL).
        x       ndarray Optimal values of the hyperparameters.
        message str     String describing the exit state (`smode` from :py:func:`fmin_slsqp`)
        nit     int     Number of iterations.
        ======= ======= ===================================================================================

    Raises
    ------
    ValueError
        Invalid constraint type in `constraints`. (See documentation for :py:func:`scipy.optimize.minimize`.)
    """
    opt_kwargs = dict(opt_kwargs)

    opt_kwargs.pop('method', None)

    eqcons = []
    ieqcons = []
    if 'constraints' in opt_kwargs:
        if isinstance(opt_kwargs['constraints'], dict):
            opt_kwargs['constraints'] = [opt_kwargs['constraints'],]
        for con in opt_kwargs.pop('constraints'):
            if con['type'] == 'eq':
                eqcons += [con['fun'],]
            elif con['type'] == 'ineq':
                ieqcons += [con['fun'],]
            else:
                raise ValueError("Invalid constraint type %s!" % (con['type'],))

    if 'jac' in opt_kwargs:
        warnings.warn("Jacobian not supported for default solver SLSQP!",
                      RuntimeWarning)
        opt_kwargs.pop('jac')

    if 'tol' in opt_kwargs:
        opt_kwargs['acc'] = opt_kwargs.pop('tol')

    if 'options' in opt_kwargs:
        opts = opt_kwargs.pop('options')
        opt_kwargs = dict(opt_kwargs.items() + opts.items())

    # Other keywords with less likelihood for causing failures are silently ignored:
    opt_kwargs.pop('hess', None)
    opt_kwargs.pop('hessp', None)
    opt_kwargs.pop('callback', None)

    out, fx, its, imode, smode = scipy.optimize.fmin_slsqp(
        fun,
        guess,
        full_output=True,
        eqcons=eqcons,
        ieqcons=ieqcons,
        **opt_kwargs
    )

    Result = collections.namedtuple('Result',
                                    ['status', 'success', 'fun', 'x', 'message', 'nit'])

    return Result(status=imode,
                  success=(imode == 0),
                  fun=fx,
                  x=out,
                  message=smode,
                  nit=its)

def incomplete_bell_poly(n, k, x):
    r"""Recursive evaluation of the incomplete Bell polynomial :math:`B_{n, k}(x)`.
    
    Evaluates the incomplete Bell polynomial :math:`B_{n, k}(x_1, x_2, \dots, x_{n-k+1})`,
    also known as the partial Bell polynomial or the Bell polynomial of the
    second kind. This polynomial is useful in the evaluation of (the univariate)
    Faa di Bruno's formula which generalizes the chain rule to higher order
    derivatives.
    
    The implementation here is based on the implementation in:
    :py:func:`sympy.functions.combinatorial.numbers.bell._bell_incomplete_poly`
    Following that function's documentation, the polynomial is computed
    according to the recurrence formula:
    
    .. math::
        
        B_{n, k}(x_1, x_2, \dots, x_{n-k+1}) = \sum_{m=1}^{n-k+1}x_m\binom{n-1}{m-1}B_{n-m, k-1}(x_1, x_2, \dots, x_{n-m-k})
        
    | The end cases are:
    | :math:`B_{0, 0} = 1`
    | :math:`B_{n, 0} = 0` for :math:`n \ge 1`
    | :math:`B_{0, k} = 0` for :math:`k \ge 1`
    
    Parameters
    ----------
    n : scalar int
        The first subscript of the polynomial.
    k : scalar int
        The second subscript of the polynomial.
    x : :py:class:`Array` of floats, (`p`, `n` - `k` + 1)
        `p` sets of `n` - `k` + 1 points to use as the arguments to
        :math:`B_{n,k}`. The second dimension can be longer than
        required, in which case the extra entries are silently ignored
        (this facilitates recursion without needing to subset the array `x`).
    
    Returns
    -------
    result : :py:class:`Array`, (`p`,)
        Incomplete Bell polynomial evaluated at the desired values.
    """
    if n == 0 and k == 0:
        return scipy.ones(x.shape[0], dtype=float)
    elif k == 0 and n >= 1:
        return scipy.zeros(x.shape[0], dtype=float)
    elif n == 0 and k >= 1:
        return scipy.zeros(x.shape[0], dtype=float)
    else:
        result = scipy.zeros(x.shape[0], dtype=float)
        for m in xrange(0, n - k + 1):
            result += x[:, m] * scipy.special.binom(n - 1, m) * incomplete_bell_poly(n - (m + 1), k - 1, x)
        return result

def generate_set_partition_strings(n):
    """Generate the restricted growth strings for all of the partitions of an `n`-member set.
    
    Uses Algorithm H from page 416 of volume 4A of Knuth's `The Art of Computer
    Programming`. Returns the partitions in lexicographical order.
    
    Parameters
    ----------
    n : scalar int, non-negative
        Number of (unique) elements in the set to be partitioned.
    
    Returns
    -------
    partitions : list of :py:class:`Array`
        List has a number of elements equal to the `n`-th Bell number (i.e.,
        the number of partitions for a set of size `n`). Each element has
        length `n`, the elements of which are the restricted growth strings
        describing the partitions of the set. The strings are returned in
        lexicographic order.
    """
    # Handle edge cases:
    if n == 0:
        return []
    elif n == 1:
        return [scipy.array([0])]
    
    partitions = []
    
    # Step 1: Initialize
    a = scipy.zeros(n, dtype=int)
    b = scipy.ones(n, dtype=int)
    
    while True:
        # Step 2: Visit
        partitions.append(a.copy())
        if a[-1] == b[-1]:
            # Step 4: Find j. j is the index of the first element from the end
            # for which a != b, with the exception of the last element.
            j = (a[:-1] != b[:-1]).nonzero()[0][-1]
            # Step 5: Increase a_j (or terminate):
            if j == 0:
                break
            else:
                a[j] += 1
                # Step 6: Zero out a_{j+1} to a_n:
                b[-1] = b[j] + (a[j] == b[j])
                a[j + 1:] = 0
                b[j + 1 :-1] = b[-1]
        else:
            # Step 3: Increase a_n:
            a[-1] += 1
    
    return partitions

def generate_set_partitions(set_):
    """Generate all of the partitions of a set.
    
    This is a helper function that utilizes the restricted growth strings from
    :py:func:`generate_set_partition_strings`. The partitions are returned in
    lexicographic order.
    
    Parameters
    ----------
    set_ : :py:class:`Array` or other Array-like, (`m`,)
        The set to find the partitions of.
    
    Returns
    -------
    partitions : list of lists of :py:class:`Array`
        The number of elements in the outer list is equal to the number of
        partitions, which is the len(`m`)^th Bell number. Each of the inner lists
        corresponds to a single possible partition. The length of an inner list
        is therefore equal to the number of blocks. Each of the arrays in an
        inner list is hence a block.
    """
    set_ = scipy.asarray(set_)
    strings = generate_set_partition_strings(len(set_))
    partitions = []
    for string in strings:
        blocks = []
        for block_num in scipy.unique(string):
            blocks.append(set_[string == block_num])
        partitions.append(blocks)
    
    return partitions

def unique_rows(arr):
    """Returns a copy of arr with duplicate rows removed.
    
    From Stackoverflow "Find unique rows in numpy.array."
    
    Parameters
    ----------
    arr : :py:class:`Array`, (`m`, `n`). The array to find the unique rows of.
    
    Returns
    -------
    unique : :py:class:`Array`, (`p`, `n`) where `p` <= `m`
        The array `arr` with duplicate rows removed.
    """
    b = scipy.ascontiguousarray(arr).view(
        scipy.dtype((scipy.void, arr.dtype.itemsize * arr.shape[1]))
    )
    try:
        dum, idx = scipy.unique(b, return_index=True)
    except TypeError:
        # Handle bug in numpy 1.6.2:
        rows = [_Row(row) for row in b]
        srt_idx = sorted(range(len(rows)), key=rows.__getitem__)
        rows = scipy.asarray(rows)[srt_idx]
        row_cmp = [-1]
        for k in xrange(1, len(srt_idx)):
            row_cmp.append(rows[k-1].__cmp__(rows[k]))
        row_cmp = scipy.asarray(row_cmp)
        transition_idxs = scipy.where(row_cmp != 0)[0]
        idx = scipy.asarray(srt_idx)[transition_idxs]
    return arr[idx]

class _Row(object):
    """Helper class to compare rows of a matrix.
    
    This is used to workaround the bug with scipy.unique in numpy 1.6.2.
    
    Parameters
    ----------
    row : ndarray
        The row this object is to represent. Must be 1d. (Will be flattened.)
    """
    def __init__(self, row):
        self.row = scipy.asarray(row).flatten()
    
    def __cmp__(self, other):
        """Compare two rows.
        
        Parameters
        ----------
        other : :py:class:`_Row`
            The row to compare to.
        
        Returns
        -------
        cmp : int
            == ==================================================================
            0  if the two rows have all elements equal
            1  if the first non-equal element (from the right) in self is greater
            -1 if the first non-equal element (from the right) in self is lesser
            == ==================================================================
        """
        if (self.row == other.row).all():
            return 0
        else:
            # Get first non-equal element:
            first_nonequal_idx = scipy.where(self.row != other.row)[0][0]
            if self.row[first_nonequal_idx] > other.row[first_nonequal_idx]:
                return 1
            else:
                # Other must be greater than self in this case:
                return -1

# Conversion factor to get from interquartile range to standard deviation:
IQR_TO_STD = 2.0 * scipy.stats.norm.isf(0.25)

def compute_stats(vals, check_nan=False, robust=False, axis=1, plot_QQ=False, bins=15):
    """Compute the average statistics (mean, std dev) for the given values.
    
    Parameters
    ----------
    vals : array-like, (`M`, `N`)
        Values to compute the average statistics along the specified axis of.
    check_nan : bool, optional
        Whether or not to check for (and exclude) NaN's. Default is False (do
        not attempt to handle NaN's).
    robust : bool, optional
        Whether or not to use robust estimators (median for mean, IQR for
        standard deviation). Default is False (use non-robust estimators).
    axis : int, optional
        Axis to compute the statistics along. Presently only supported if
        `robust` is False. Default is 1.
    plot_QQ : bool, optional
        Whether or not a QQ plot should be drawn for each channel. Default is
        False (do not draw QQ plots).
    bins : int, optional
        Number of bins to use when plotting histogram (for plot_QQ=True).
        Default is 15
    
    Returns
    -------
    mean : ndarray, (`M`,)
        Estimator for the mean of `vals`.
    std : ndarray, (`M`,)
        Estimator for the standard deviation of `vals`.
    
    Raises
    ------
    NotImplementedError
        If `axis` != 1 when `robust` is True.
    NotImplementedError
        If `plot_QQ` is True.
    """
    if axis != 1 and robust:
        raise NotImplementedError("Values of axis other than 1 are not supported "
                                  "with the robust keyword at this time!")
    if robust:
        # TODO: This stuff should really be vectorized if there is something that allows it!
        if check_nan:
            mean = scipy.stats.nanmedian(vals, axis=axis)
            # TODO: HANDLE AXIS PROPERLY!
            std = scipy.zeros(vals.shape[0], dtype=float)
            for k in xrange(0, len(vals)):
                ch = vals[k]
                ok_idxs = ~scipy.isnan(ch)
                if ok_idxs.any():
                    std[k] = (scipy.stats.scoreatpercentile(ch[ok_idxs], 75) -
                              scipy.stats.scoreatpercentile(ch[ok_idxs], 25))
                else:
                    # Leave a nan where there are no non-nan values:
                    std[k] = scipy.nan
            std /= IQR_TO_STD
        else:
            mean = scipy.median(vals, axis=axis)
            # TODO: HANDLE AXIS PROPERLY!
            std = scipy.asarray([scipy.stats.scoreatpercentile(ch, 75.0) -
                                 scipy.stats.scoreatpercentile(ch, 25.0)
                                 for ch in vals]) / IQR_TO_STD
    else:
        if check_nan:
            mean = scipy.stats.nanmean(vals, axis=axis)
            std = scipy.stats.nanstd(vals, axis=axis)
        else:
            mean = scipy.mean(vals, axis=axis)
            std = scipy.std(vals, axis=axis)
    if plot_QQ:
        f = plt.figure()
        gs = mplgs.GridSpec(2, 2, height_ratios=[8, 1])
        a_QQ = f.add_subplot(gs[0, 0])
        a_hist = f.add_subplot(gs[0, 1])
        a_slider = f.add_subplot(gs[1, :])
        
        title = f.suptitle("")
        
        def update(val):
            """Update the index from the results to be displayed.
            """
            a_QQ.clear()
            a_hist.clear()
            idx = slider.val
            title.set_text("n=%d" % idx)
            
            osm, osr = scipy.stats.probplot(vals[idx, :], dist='norm', plot=None, fit=False)
            a_QQ.plot(osm, osr, 'bo', markersize=10)
            a_QQ.set_title('QQ plot')
            a_QQ.set_xlabel('quantiles of $\mathcal{N}(0,1)$')
            a_QQ.set_ylabel('quantiles of data')
            
            a_hist.hist(vals[idx, :], bins=bins, normed=True)
            locs = scipy.linspace(vals[idx, :].min(), vals[idx, :].max())
            a_hist.plot(locs, scipy.stats.norm.pdf(locs, loc=mean[idx], scale=std[idx]))
            a_hist.set_title('Normalized histogram and reported PDF')
            a_hist.set_xlabel('value')
            a_hist.set_ylabel('density')
            
            f.canvas.draw()
        
        def arrow_respond(slider, event):
            """Event handler for arrow key events in plot windows.

            Pass the slider object to update as a masked argument using a lambda function::

                lambda evt: arrow_respond(my_slider, evt)

            Parameters
            ----------
            slider : Slider instance associated with this handler.
            event : Event to be handled.
            """
            if event.key == 'right':
                slider.set_val(min(slider.val + 1, slider.valmax))
            elif event.key == 'left':
                slider.set_val(max(slider.val - 1, slider.valmin))

        slider = mplw.Slider(a_slider,
                             'index',
                             0,
                             len(vals) - 1,
                             valinit=0,
                             valfmt='%d')
        slider.on_changed(update)
        update(0)
        f.canvas.mpl_connect('key_press_event', lambda evt: arrow_respond(slider, evt))
    
    return (mean, std)
