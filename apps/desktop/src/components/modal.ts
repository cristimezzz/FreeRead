// 当前是否有模态对话框打开：全局快捷键此时让给对话框。遮罩只在对话框打开时渲染。

export function isModalOpen(): boolean {
  return document.querySelector('[data-slot="dialog-overlay"]') !== null;
}
