import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  new URL('./KnowledgeDetailView.vue', import.meta.url),
  'utf8',
)

describe('knowledge detail layout', () => {
  it('opens the default strategy from a compact summary drawer', () => {
    expect(source).toContain('strategy-summary')
    expect(source).toContain('v-model:show="strategyDrawerVisible"')
    expect(source).toContain('@click="openStrategyDrawer"')
    expect(source).toContain('@after-leave="resetKnowledgeStrategy"')
  })

  it('keeps raw source in its own column beside processing results', () => {
    expect(source).toContain('class="preview-source-column"')
    expect(source).toContain('class="preview-result-column"')
    expect(source).toContain('<h3>原文</h3>')
    expect(source).not.toContain('name="raw" tab="原文"')
    expect(source).toContain('name="cleaned" tab="清洗结果"')
  })

  it('fills the preview drawer body instead of capping columns at 650px', () => {
    expect(source).toContain('width="min(1180px, 100vw)"')
    expect(source).toContain('body-content-style="height: 100%; overflow: hidden;"')
    expect(source).toContain('.preview-layout { display: grid;')
    expect(source).toContain('height: 100%; min-height: 0;')
    expect(source).not.toContain('max-height: 650px')
  })
})
