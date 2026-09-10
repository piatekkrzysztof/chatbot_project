"""OS limits for the child parser only; never call in a Django/Celery process."""

import os

_WINDOWS_JOB = None


def apply_limits(memory_bytes, cpu_seconds=15):
    if os.name != "nt":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
        return

    # Development/tests on Windows use the same fail-closed memory policy.
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("ProcessTime", ctypes.c_longlong),
            ("JobTime", ctypes.c_longlong),
            ("Flags", wintypes.DWORD),
            ("MinWorkingSet", ctypes.c_size_t),
            ("MaxWorkingSet", ctypes.c_size_t),
            ("ActiveProcesses", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("Priority", wintypes.DWORD),
            ("Scheduling", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("Basic", BasicLimits),
            ("IO", ctypes.c_ulonglong * 6),
            ("ProcessMemory", ctypes.c_size_t),
            ("JobMemory", ctypes.c_size_t),
            ("PeakProcessMemory", ctypes.c_size_t),
            ("PeakJobMemory", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = ExtendedLimits()
    # Per-process memory, one process, CPU time, kill on job close.
    info.Basic.Flags = 0x100 | 0x8 | 0x2 | 0x2000
    info.Basic.ActiveProcesses = 1
    info.Basic.ProcessTime = cpu_seconds * 10_000_000
    info.ProcessMemory = memory_bytes
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    global _WINDOWS_JOB
    _WINDOWS_JOB = job  # Keep the handle alive until the child exits.
