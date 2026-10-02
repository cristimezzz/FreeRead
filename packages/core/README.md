# @freeread/core

M0 导出 BUDGETS、AppError/错误信封、生成的领域与 IPC 类型及通道清单。唯一出口为 src/index.ts。
纯逻辑与纯类型，不访问 UI/Electron/文件系统/网络；锚点与进度业务在 M1/M2 实现。

依赖方向与职责见 [架构规范](../../specs/01-architecture.md)。
