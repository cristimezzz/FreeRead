import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
    // material-color-utilities 0.4 的 ESM 用了不带扩展名的相对导入，Node 解析不了，交给 Vite 转换
    server: { deps: { inline: ["@material/material-color-utilities"] } },
  },
});
