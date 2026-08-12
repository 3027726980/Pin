/**
 * widget 独立构建配置：产出单文件 widget.js（IIFE，无代码分割）
 * 输出到 backend/static/widget/（后端静态托管）
 */
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

export default defineConfig({
  build: {
    outDir: fileURLToPath(new URL('../backend/static/widget', import.meta.url)),
    emptyOutDir: true,
    lib: {
      entry: fileURLToPath(new URL('./src/widget/index.ts', import.meta.url)),
      name: 'PinWidget',
      formats: ['iife'],
      fileName: () => 'widget.js',
    },
    // widget 无外部依赖，全部内联；产物体积优先
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
    target: 'es2019',
    minify: 'esbuild',
    sourcemap: false,
  },
})
