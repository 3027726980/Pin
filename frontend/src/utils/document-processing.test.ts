import { describe, expect, it } from 'vitest'
import contract from '../../../contracts/document-processing/v1.json'
import {
  PROCESSING_ALGORITHM_VERSION,
  buildDocumentPreview,
  type ProcessingConfig,
} from './document-processing'

describe('document processing v1 contract', () => {
  it('matches every shared cleaning and splitting case', () => {
    expect(PROCESSING_ALGORITHM_VERSION).toBe(contract.algorithm_version)
    for (const testCase of contract.cases) {
      const result = buildDocumentPreview(
        testCase.raw_text,
        testCase.processing_config as ProcessingConfig,
      )
      expect(result.cleanedText, testCase.name).toBe(testCase.expected_cleaned_text)
      expect(result.chunks, testCase.name).toEqual(
        testCase.expected_chunks.map((chunk, index) => ({ index, ...chunk })),
      )
    }
  })
})
