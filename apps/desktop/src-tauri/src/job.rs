//! Windows Job Object：壳进程崩溃或被 `taskkill /F` 时，由系统关闭最后一个
//! job 句柄并结束 job 内的全部进程（包括 sidecar 派生的子进程，如 MinerU worker）。

use std::ptr;

use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
    SetInformationJobObject, TerminateJobObject,
};
use windows_sys::Win32::System::Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE};

pub struct Job(HANDLE);

// HANDLE 是裸指针；job 句柄可以在线程间安全共享。
unsafe impl Send for Job {}
unsafe impl Sync for Job {}

impl Job {
    pub fn new_kill_on_close() -> std::io::Result<Self> {
        unsafe {
            let handle = CreateJobObjectW(ptr::null(), ptr::null());
            if handle.is_null() {
                return Err(std::io::Error::last_os_error());
            }
            let job = Job(handle);
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let ok = SetInformationJobObject(
                job.0,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const _,
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            );
            if ok == 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(job)
        }
    }

    pub fn assign_pid(&self, pid: u32) -> std::io::Result<()> {
        unsafe {
            let process = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
            if process.is_null() {
                return Err(std::io::Error::last_os_error());
            }
            let ok = AssignProcessToJobObject(self.0, process);
            let err = std::io::Error::last_os_error();
            CloseHandle(process);
            if ok == 0 { Err(err) } else { Ok(()) }
        }
    }

    /// 结束 job 内所有进程（正常退出路径）。
    pub fn terminate(&self) {
        unsafe {
            TerminateJobObject(self.0, 1);
        }
    }
}

impl Drop for Job {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}
