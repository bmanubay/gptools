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

"""Core kernel classes: contains the base :py:class:`Kernel` class and helper subclasses.
"""

from __future__ import division

from ..utils import unique_rows, generate_set_partitions, UniformPrior
from ..error_handling import GPArgumentError

import scipy
import scipy.special
try:
    import mpmath
except ImportError:
    import warnings
    warnings.warn("Could not import mpmath. ArbitraryKernel class will not work.",
                  ImportWarning)
import inspect
import multiprocessing

class Kernel(object):
    """Covariance kernel base class. Not meant to be explicitly instantiated!
    
    Initialize the kernel with the given number of input dimensions.
    
    Parameters
    ----------
    num_dim : positive int
        Number of dimensions of the input data. Must be consistent with the `X`
        and `Xstar` values passed to the :py:class:`~gptools.gaussian_process.GaussianProcess` you wish
        to use the covariance kernel with.
    num_params : Non-negative int
        Number of parameters in the model.
    initial_params : :py:class:`Array` or other Array-like, (`num_params`,), optional
        Initial values to set for the hyperparameters. Default is None, in
        which case 1 is used for the initial values.
    fixed_params : :py:class:`Array` or other Array-like of bool, (`num_params`,), optional
        Sets which parameters are considered fixed when optimizing the log
        likelihood. A True entry corresponds to that element being
        fixed (where the element ordering is as defined in the class).
        Default value is None (no parameters are fixed).
    param_bounds : list of 2-tuples (`num_params`,), optional
        List of bounds for each of the parameters. Each 2-tuple is of the form
        (`lower`, `upper`). If there is no bound in a given direction, set it
        to double_max. Default is (0.0, double_max) for each parameter.
    enforce_bounds : bool, optional
        If True, an attempt to set a parameter outside of its bounds will
        result in the parameter being set right at its bound. If False, bounds
        are not enforced inside the kernel. Default is False (do not enforce
        bounds).
    hyperpriors : list of callables (`num_params`,), optional
        List of functions that return the prior probability density for the
        corresponding hyperparameter when evaluated. The function is called
        with only the single hyperparameter (or a list of values) as an
        argument, which permits use of standard PDFs from :py:mod:`scipy.stats`.
        This does, however, require that the hyperparameters be treated as
        independent. Note that what is actually computed is the logarithm of
        the posterior density, so your PDF cannot be zero anywhere that it
        might get evaluated. You can choose to specify either the distribution
        or the log of the distribution by setting the `is_log` keyword.
        Default value is uniform PDF on all hyperparameters.
    is_log : list of bool (`num_params`,), optional
        Indicates whether the corresponding hyperprior returns the density or
        the log-density. Default is `True` for each parameter: all hyperpriors
        return log-density.
    potentials : list of callables, optional
        List of functions that return log-densities that are added onto the
        posterior log-density. Must take the vector of hyperparameters as the
        only argument and return a single value of log-density. Default is []
        (no potentials).
    
    Attributes
    ----------
    num_params : int
        Number of parameters
    num_dim : int
        Number of dimensions
    params : :py:class:`Array` of float, (`num_params`,)
        Array of parameters.
    fixed_params : :py:class:`Array` of bool, (`num_params`,)
        Array of booleans indicated which parameters in params are fixed.
    param_bounds : list of 2-tuples, (`num_params`,)
        List of bounds for the parameters in params.
    hyperpriors : list of callables, (`num_params`,)
        List of prior functions for the hyperparameters.
    is_log : list of bool, (`num_params`,)
        List of flags for if the hyperpriors return density or log-density.
    
    Raises
    ------
    ValueError
        If `num_dim` is not a positive integer or the lengths of the input
        vectors are inconsistent.
        
    GPArgumentError
        if `fixed_params` is passed but `initial_params` is not.
    """
    def __init__(self, num_dim=1, num_params=0, initial_params=None,
                 fixed_params=None, param_bounds=None, enforce_bounds=False,
                 hyperpriors=None, is_log=None, potentials=[]):
        if num_params < 0 or not isinstance(num_params, (int, long)):
            raise ValueError("num_params must be an integer >= 0!")
        self.num_params = num_params
        if num_dim < 1 or not isinstance(num_dim, (int, long)):
            raise ValueError("num_dim must be an integer > 0!")
        self.num_dim = num_dim
        
        self.enforce_bounds = enforce_bounds
        
        # Handle default case for initial parameter values -- set them all to 1.
        if initial_params is None:
            # Only accept fixed_params if initial_params is given:
            if fixed_params is not None:
                raise GPArgumentError("Must pass explicit parameter values "
                                         "if fixing parameters!")
            initial_params = scipy.ones(num_params, dtype=float)
            fixed_params = scipy.zeros(num_params, dtype=float)
        else:
            if len(initial_params) != num_params:
                raise ValueError("Length of initial_params must be equal to the num_params!")
            # Handle default case of fixed_params: no fixed parameters.
            if fixed_params is None:
                fixed_params = scipy.zeros(num_params, dtype=float)
            else:
                if len(fixed_params) != num_params:
                    raise ValueError("Length of fixed_params must be equal to num_params!")
        
        # Handle default case for parameter bounds -- set them all to (0, double_max):
        if param_bounds is None:
            param_bounds = num_params * [(0.0, scipy.finfo('d').max)]
        else:
            if len(param_bounds) != num_params:
                raise ValueError("Length of param_bounds must be equal to num_params!")
        
        # Handle default case for hyperpriors -- set them all to be uniform:
        if hyperpriors is None:
            hyperpriors = [UniformPrior(b) for b in param_bounds]
        else:
            if len(hyperpriors) != num_params:
                raise ValueError("Length of hyperpriors must be equal to num_params!")
        
        # Handle default case for is_log -- set them all to be density:
        if is_log is None:
            is_log = num_params * [True]
        else:
            if len(is_log) != num_params:
                raise ValueError("Length of is_log must be equal to num_params!")
        
        self.params = scipy.asarray(initial_params, dtype=float)
        self.fixed_params = scipy.asarray(fixed_params, dtype=bool)
        self.param_bounds = param_bounds
        self.hyperpriors = hyperpriors
        self.is_log = is_log
        self.potentials = potentials
    
    def __call__(self, Xi, Xj, ni, nj, hyper_deriv=None, symmetric=False):
        """Evaluate the covariance between points `Xi` and `Xj` with derivative order `ni`, `nj`.
        
        Parameters
        ----------
        Xi : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` inputs with dimension `N`.
        Xj : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` inputs with dimension `N`.
        ni : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` derivative orders for set `i`.
        nj : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` derivative orders for set `j`.
        hyper_deriv : Non-negative int or None, optional
            The index of the hyperparameter to compute the first derivative
            with respect to. If None, no derivatives are taken. Default is None
            (no hyperparameter derivatives).
        symmetric : bool, optional
            Whether or not the input `Xi`, `Xj` are from a symmetric matrix.
            Default is False.
        
        Returns
        -------
        Kij : :py:class:`Array`, (`M`,)
            Covariances for each of the `M` `Xi`, `Xj` pairs.
        
        Notes
        -----
        THIS IS ONLY A METHOD STUB TO DEFINE THE NEEDED CALLING FINGERPRINT!
        """
        raise NotImplementedError("This is an abstract method -- please use "
                                  "one of the implementing subclasses!")
    
    def set_hyperparams(self, new_params):
        """Sets the free hyperparameters to the new parameter values in new_params.

        Parameters
        ----------
        new_params : :py:class:`Array` or other Array-like, (len(:py:attr:`self.params`),)
            New parameter values, ordered as dictated by the docstring for the
            class.
        """
        new_params = scipy.asarray(new_params, dtype=float)
        
        if new_params.shape == self.free_params.shape:
            if self.enforce_bounds:
                for idx, new_param, bound in zip(range(0, len(new_params)), new_params, self.free_param_bounds):
                    if bound[0] is not None and new_param < bound[0]:
                        new_params[idx] = bound[0]
                    elif bound[1] is not None and new_param > bound[1]:
                        new_params[idx] = bound[1]
            self.params[~self.fixed_params] = new_params
        else:
            raise ValueError("Length of new_params must be %s!" % (self.params.shape,))
    
    @property
    def free_params(self):
        """Returns the values of the free hyperparameters.
        
        Returns
        -------
        free_params : :py:class:`Array`
            Array of the free parameters, in order.
        """
        return self.params[~self.fixed_params]
    
    @property
    def free_param_bounds(self):
        """Returns the bounds of the free hyperparameters.
        
        Returns
        -------
        free_param_bounds : :py:class:`Array`
            Array of the bounds of the free parameters, in order.
        """
        return scipy.asarray(self.param_bounds, dtype=float)[~self.fixed_params]
    
    def __add__(self, other):
        """Add two Kernels together.
        
        Parameters
        ----------
        other : :py:class:`Kernel`
            Kernel to be added to this one.
        
        Returns
        -------
        sum : :py:class:`SumKernel`
            Instance representing the sum of the two kernels.
        """
        return SumKernel(self, other)
    
    def __mul__(self, other):
        """Multiply two Kernels together.
        
        Parameters
        ----------
        other : :py:class:`Kernel`
            Kernel to be multiplied by this one.
        
        Returns
        -------
        prod : :py:class:`ProductKernel`
            Instance representing the product of the two kernels.
        """
        return ProductKernel(self, other)
    
    def _compute_r2l2(self, tau, return_l=False):
        r"""Compute the anisotropic :math:`r^2/l^2` term for the given `tau`.
        
        Here, :math:`\tau=X_i-X_j` is the difference vector. Computes
        .. math::
            \frac{r^2}{l^2} = \sum_i\frac{\tau_i^2}{l_{i}^{2}}
        Assumes that the length parameters are the last `num_dim` elements of
        :py:attr:`self.params`.
        
        Parameters
        ----------
        tau : :py:class:`Array`, (`M`, `N`)
            `M` inputs with dimension `N`.
        return_l : bool, optional
            Set to True to return a tuple of (`tau`, `l_mat`), where `l_mat`
            is the matrix of length scales to match the shape of `tau`. Default
            is False (only return `tau`).
        
        Returns
        -------
        r2l2 : :py:class:`Array`, (`M`,)
            Anisotropically scaled distances squared.
        l_mat : :py:class:`Array`, (`M`, `N`)
            The (`N`,) array of length scales repeated for each of the `M`
            inputs. Only returned if `return_l` is True.
        """
        l_mat = scipy.tile(self.params[-self.num_dim:], (tau.shape[0], 1))
        r2l2 = scipy.sum((tau / l_mat)**2, axis=1)
        if return_l:
            return (r2l2, l_mat)
        else:
            return r2l2

class BinaryKernel(Kernel):
    """Abstract class for binary operations on kernels (addition, multiplication, etc.).
    
    Parameters
    ----------
    k1, k2 : :py:class:`Kernel` instances to be combined
    
    Notes
    -----
    `k1` and `k2` must have the same number of dimensions.
    """
    def __init__(self, k1, k2):
        """
        """
        if not isinstance(k1, Kernel) or not isinstance(k2, Kernel):
            raise TypeError("Both arguments to SumKernel must be instances of "
                            "type Kernel!")
        if k1.num_dim != k2.num_dim:
            raise ValueError("Only kernels having the same number of dimensions "
                             "can be summed!")
        self.k1 = k1
        self.k2 = k2
        
        super(BinaryKernel, self).__init__(num_dim=k1.num_dim,
                                           num_params=k1.num_params + k2.num_params,
                                           initial_params=scipy.concatenate((k1.params, k2.params)),
                                           fixed_params=scipy.concatenate((k1.fixed_params, k2.fixed_params)),
                                           param_bounds=list(k1.param_bounds) + list(k2.param_bounds),
                                           hyperpriors=list(k1.hyperpriors) + list(k2.hyperpriors),
                                           is_log=list(k1.is_log) + list(k2.is_log))
    
    def set_hyperparams(self, new_params):
        """Set the (free) hyperparameters.
        
        Parameters
        ----------
        new_params : :py:class:`Array` or other Array-like
            New values of the free parameters.
        
        Raises
        ------
        ValueError
            If the length of `new_params` is not consistent with :py:attr:`self.params`.
        """
        new_params = scipy.asarray(new_params, dtype=float)
        
        if new_params.shape == self.free_params.shape:
            self.params[~self.fixed_params] = new_params
            num_fixed_k1 = sum(~self.k1.fixed_params)
            self.k1.set_hyperparams(new_params[:num_fixed_k1])
            self.k2.set_hyperparams(new_params[num_fixed_k1:])
        else:
            raise ValueError("Length of new_params must be %s!" % (self.params.shape,))

class SumKernel(BinaryKernel):
    """The sum of two kernels.
    """
    def __call__(self, *args, **kwargs):
        """Evaluate the covariance between points `Xi` and `Xj` with derivative order `ni`, `nj`.
        
        Parameters
        ----------
        Xi : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` inputs with dimension `N`.
        Xj : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` inputs with dimension `N`.
        ni : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` derivative orders for set `i`.
        nj : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` derivative orders for set `j`.
        symmetric : bool, optional
            Whether or not the input `Xi`, `Xj` are from a symmetric matrix.
            Default is False.
        
        Returns
        -------
        Kij : :py:class:`Array`, (`M`,)
            Covariances for each of the `M` `Xi`, `Xj` pairs.
        
        Raises
        ------
        NotImplementedError
            If the `hyper_deriv` keyword is given and is not None.
        """
        if 'hyper_deriv' in kwargs and kwargs['hyper_deriv'] is not None:
            raise NotImplementedError("Keyword hyper_deriv is not presently "
                                      "supported for SumKernel!")
        return self.k1(*args, **kwargs) + self.k2(*args, **kwargs)

class ProductKernel(BinaryKernel):
    """The product of two kernels.
    """
    def __call__(self, *args, **kwargs):
        """Evaluate the covariance between points `Xi` and `Xj` with derivative order `ni`, `nj`.
        
        Parameters
        ----------
        Xi : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` inputs with dimension `N`.
        Xj : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` inputs with dimension `N`.
        ni : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` derivative orders for set `i`.
        nj : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` derivative orders for set `j`.
        symmetric : bool, optional
            Whether or not the input `Xi`, `Xj` are from a symmetric matrix.
            Default is False.
        
        Returns
        -------
        Kij : :py:class:`Array`, (`M`,)
            Covariances for each of the `M` `Xi`, `Xj` pairs.
        
        Raises
        ------
        NotImplementedError
            If the `hyper_deriv` keyword is given and is not None.
        """
        return self.k1(*args, **kwargs) * self.k2(*args, **kwargs)

class ChainRuleKernel(Kernel):
    """Abstract class for the common methods in creating kernels that require application of Faa di Bruno's formula.
    """
    def __call__(self, Xi, Xj, ni, nj, hyper_deriv=None, symmetric=False):
        """Evaluate the covariance between points `Xi` and `Xj` with derivative order `ni`, `nj`.
        
        Parameters
        ----------
        Xi : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` inputs with dimension `N`.
        Xj : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` inputs with dimension `N`.
        ni : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` derivative orders for set `i`.
        nj : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` derivative orders for set `j`.
        hyper_deriv : Non-negative int or None, optional
            The index of the hyperparameter to compute the first derivative
            with respect to. If None, no derivatives are taken. Hyperparameter
            derivatives are not supported at this point. Default is None.
        symmetric : bool
            Whether or not the input `Xi`, `Xj` are from a symmetric matrix.
            Default is False.
        
        Returns
        -------
        Kij : :py:class:`Array`, (`M`,)
            Covariances for each of the `M` `Xi`, `Xj` pairs.
        
        Raises
        ------
        NotImplementedError
            If the `hyper_deriv` keyword is not None.
        """
        if hyper_deriv is not None:
            raise NotImplementedError("Hyperparameter derivatives have not been implemented!")

        tau = scipy.asarray(Xi - Xj, dtype=float)

        # Account for derivatives:
        # Get total number of differentiations:
        n_tot_j = scipy.asarray(scipy.sum(nj, axis=1), dtype=int).flatten()
        n_combined = scipy.asarray(ni + nj, dtype=int)
        n_combined_unique = unique_rows(n_combined)

        # Evaluate the kernel:
        k = scipy.zeros(Xi.shape[0], dtype=float)
        # First compute dk/dtau
        for n_combined_state in n_combined_unique:
            idxs = (n_combined == n_combined_state).all(axis=1)
            k[idxs] = self._compute_dk_dtau(tau[idxs], n_combined_state)
        
        # Compute factor from the dtau_d/dx_d_j terms in the chain rule:
        j_chain_factors = (-1.0)**(n_tot_j)
        
        # Multiply by the chain rule factor to get dk/dXi or dk/dXj:
        k = (self.params[0])**2.0 * j_chain_factors * k
        return k
    
    def _compute_dk_dtau(self, tau, n):
        r"""Evaluate :math:`dk/d\tau` at the specified locations with the specified derivatives.

        Parameters
        ----------
        tau : :py:class:`Matrix`, (`M`, `N`)
            `M` inputs with dimension `N`.
        n : :py:class:`Array`, (`N`,)
            Degree of derivative with respect to each dimension.

        Returns
        -------
            dk_dtau : :py:class:`Array`, (`M`,)
                Specified derivative at specified locations.
        """
        # Construct the derivative pattern:
        # For each dimension, this will contain the index of the dimension
        # repeated a number of times equal to the order of derivative with
        # respect to that dimension.
        # Example: For d^3 k(x, y, z) / dx^2 dy, n would be [2, 1, 0] and
        # deriv_pattern should be [0, 0, 1]. For k(x, y, z) deriv_pattern is [].
        deriv_pattern = []
        for idx in xrange(0, len(n)):
            deriv_pattern.extend(n[idx] * [idx])
        deriv_pattern = scipy.asarray(deriv_pattern, dtype=int)
        # Handle non-derivative case separately for efficiency:
        if len(deriv_pattern) == 0:
            return self._compute_k(tau)
        else:
            # Compute all partitions of the deriv_pattern:
            deriv_partitions = generate_set_partitions(deriv_pattern)
            # Compute the requested derivative using the multivariate Faa di Bruno's equation:
            dk_dtau = scipy.zeros(tau.shape[0])
            # Loop over the partitions:
            for partition in deriv_partitions:
                dk_dtau += self._compute_dk_dtau_on_partition(tau, partition)
            return dk_dtau
    
    def _compute_dk_dtau_on_partition(self, tau, p):
        """Evaluate the term inside the sum of Faa di Bruno's formula for the given partition.

        Parameters
        ----------
        tau : :py:class:`Matrix`, (`M`, `N`)
            `M` inputs with dimension `N`.
        p : list of :py:class:`Array`
            Each element is a block of the partition representing the
            derivative orders to use.
        
        Returns
        -------
        dk_dtau : :py:class:`Array`, (`M`,)
            The specified derivatives over the given partition at the specified
            locations.
        """
        y, r2l2 = self._compute_y(tau, return_r2l2=True)
        # Compute the d^(|pi|)f/dy term:
        dk_dtau = self._compute_dk_dy(y, len(p))
        # Multiply in each of the block terms:
        for b in p:
            dk_dtau *= self._compute_dy_dtau(tau, b, r2l2)
        return dk_dtau

class ArbitraryKernel(Kernel):
    """Covariance kernel from an arbitrary covariance function.
    
    Computes derivatives using :py:func:`mpmath.diff` and is hence in general
    much slower than a hard-coded implementation of a given kernel.
    
    Parameters
    ----------
    num_dim : positive int
        Number of dimensions of the input data. Must be consistent with the `X`
        and `Xstar` values passed to the
        :py:class:`~gptools.gaussian_process.GaussianProcess` you wish to use
        the covariance kernel with.
    cov_func : callable, takes >= 2 args
        Covariance function. Must take arrays of `Xi` and `Xj` as the
        first two arguments. The subsequent (scalar) arguments are the
        hyperparameters. The number of parameters is found by inspection of
        `cov_func` itself, or with the num_params keyword.
    num_proc : int or None, optional
        Number of procs to use in evaluating covariance derivatives. 0 means
        to do it in serial, None means to use all available cores. Default is
        0 (serial evaluation).
    num_params : int or None, optional
        Number of hyperparameters. If None, inspection will be used to infer
        the number of hyperparameters (but will fail if you used clever business
        with *args, etc.). Default is None (use inspection to find argument
        count).
    **kwargs
        All other keyword parameters are passed to :py:class:`~gptools.kernel.core.Kernel`.
    
    Attributes
    ----------
    cov_func : callable
        The covariance function
    num_proc : non-negative int
        Number of processors to use in evaluating covariance derivatives. 0 means serial.
    """
    def __init__(self, cov_func, num_dim=1, num_proc=0, num_params=None, **kwargs):
        if num_proc is None:
            num_proc = multiprocessing.cpu_count()
        self.num_proc = num_proc
        if num_params is None:
            try:
                num_params = len(inspect.getargspec(cov_func)[0]) - 2
            except TypeError:
                # Need to remove self from the arg list for bound method:
                num_params = len(inspect.getargspec(cov_func.__call__)[0]) - 3
        self.cov_func = cov_func
        super(ArbitraryKernel, self).__init__(num_dim=num_dim,
                                              num_params=num_params,
                                              **kwargs)
    
    def __call__(self, Xi, Xj, ni, nj, hyper_deriv=None, symmetric=False):
        """Evaluate the covariance between points `Xi` and `Xj` with derivative order `ni`, `nj`.
        
        Parameters
        ----------
        Xi : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` inputs with dimension `N`.
        Xj : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` inputs with dimension `N`.
        ni : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` derivative orders for set `i`.
        nj : :py:class:`Matrix` or other Array-like, (`M`, `N`)
            `M` derivative orders for set `j`.
        hyper_deriv : Non-negative int or None, optional
            The index of the hyperparameter to compute the first derivative
            with respect to. If None, no derivatives are taken. Hyperparameter
            derivatives are not supported at this point. Default is None.
        symmetric : bool, optional
            Whether or not the input `Xi`, `Xj` are from a symmetric matrix.
            Default is False.
        
        Returns
        -------
        Kij : :py:class:`Array`, (`M`,)
            Covariances for each of the `M` `Xi`, `Xj` pairs.
        
        Raises
        ------
        NotImplementedError
            If the `hyper_deriv` keyword is not None.
        """
        if hyper_deriv is not None:
            raise NotImplementedError("Hyperparameter derivatives have not been implemented!")
        n_cat = scipy.asarray(scipy.concatenate((ni, nj), axis=1), dtype=int)
        X_cat = scipy.asarray(scipy.concatenate((Xi, Xj), axis=1), dtype=float)
        n_cat_unique = unique_rows(n_cat)
        k = scipy.zeros(Xi.shape[0], dtype=float)
        # Loop over unique derivative patterns:
        if self.num_proc > 0:
            pool = multiprocessing.Pool(processes=self.num_proc)
        for n_cat_state in n_cat_unique:
            idxs = scipy.where(scipy.asarray((n_cat == n_cat_state).all(axis=1)).squeeze())[0]
            if (n_cat_state == 0).all():
                k[idxs] = self.cov_func(Xi[idxs, :], Xj[idxs, :], *self.params)
            else:
                if self.num_proc > 0 and len(idxs) > 1:
                    k[idxs] = scipy.asarray(
                        pool.map(_ArbitraryKernelEval(self, n_cat_state), X_cat[idxs, :]),
                        dtype=float
                    )
                else:
                    for idx in idxs:
                        k[idx] = mpmath.chop(mpmath.diff(self._mask_cov_func,
                                                         X_cat[idx, :],
                                                         n=n_cat_state,
                                                         singular=True))
        
        if self.num_proc > 0:
            pool.close()
        return k
    
    def _mask_cov_func(self, *args):
        """Masks the covariance function into a form usable by :py:func:`mpmath.diff`.
        
        Parameters
        ----------
        *args : `num_dim` * 2 floats
            The individual elements of Xi and Xj to be passed to :py:attr:`cov_func`.
        """
        # Have to do it in two cases to get the 1d unwrapped properly:
        if self.num_dim == 1:
            return self.cov_func(args[0], args[1], *self.params)
        else:
            return self.cov_func(args[:self.num_dim], args[self.num_dim:], *self.params)

class _ArbitraryKernelEval(object):
    """Helper class to support parallel evaluation of the :py:class:ArbitraryKernel:.
    
    Parameters
    ----------
    obj : :py:class:Kernel: instance
        Instance to warp to allow parallel computation of.
    n_cat_state : Array-like, (2,)
        Derivative orders to take with respect to `Xi` and `Xj`.
    """
    # TODO: Generalize this for higher dimensions, since ArbitraryKernel is
    # supposed to be more general than univariate.
    def __init__(self, obj, n_cat_state):
        self.obj = obj
        self.n_cat_state = n_cat_state
    
    def __call__(self, X_cat_row):
        """Return the covariance function of object evaluated at the given `X_cat_row`.
        
        Parameters
        ----------
        X_cat_row : Array-like, (2,)
            The `Xi` and `Xj` point to evaluate at.
        """
        return mpmath.chop(mpmath.diff(self.obj._mask_cov_func,
                                       X_cat_row,
                                       n=self.n_cat_state,
                                       singular=True))
