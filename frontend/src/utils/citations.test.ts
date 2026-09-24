import { describe, expect, it } from 'vitest'

import { stripUnboundSourceMarkers } from './citations'

describe('stripUnboundSourceMarkers', () => {
  it('removes all stable markers when this turn has no bindings', () => {
    expect(stripUnboundSourceMarkers('历史资料 [S1]，另见[S9]。')).toBe('历史资料，另见。')
  })

  it('keeps only markers backed by this turn bindings', () => {
    expect(stripUnboundSourceMarkers('有效[S1]，无效[S9]。', ['S1'])).toBe('有效[S1]，无效。')
  })
})
