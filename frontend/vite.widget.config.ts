/**
 * widget 独立构建配置：产出单文件 widget.js（IIFE，无代码分割）
 * 输出到 backend/static/widget/（后端静态托管）
 */
import { resolve } from 'path'
import { defineConfig } from 'vite'

export default defineConfig({
  build: {
    outDir: resolve(__dirname, '../backend/static/widget'),
    emptyOutDir: true,
    lib: {
      entry: resolve(__dirname, 'src/widget/index.ts'),
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
