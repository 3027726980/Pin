import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const source = readFileSync(
  fileURLToPath(new URL('./KnowledgeListView.vue', import.meta.url)),
  'utf-8',
)

describe('KnowledgeListView embedding selector', () => {
  it('locks the embedding selector and explains why while editing', () => {
    expect(source).toContain(':disabled="!!editingId"')
    expect(source).toContain('v-if="editingId" class="embedding-lock-hint"')
    expect(source).toContain('创建后不可修改')
  })
})
