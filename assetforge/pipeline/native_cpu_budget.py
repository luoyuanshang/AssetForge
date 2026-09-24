"""Keep native numerical libraries from multiplying every network worker by 64."""
import os

THREAD_ENV = (
    'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS',
    'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS',
)


def bounded_native_environment(base):
    """Return a copy; request concurrency and all other settings stay intact."""
    result = dict(base)
    result.update({key: '1' for key in THREAD_ENV})
    return result


def install_native_cpu_budget():
    """Call before importing provider/runtime modules that may load BLAS."""
    os.environ.update({key: '1' for key in THREAD_ENV})
