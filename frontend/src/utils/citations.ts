/** 移除没有本轮结构化绑定支撑的稳定来源标记。 */
export function stripUnboundSourceMarkers(content: string, validSourceIds: Iterable<string> = []): string {
  const valid = new Set(validSourceIds)
  const sanitized = content.replace(/\[(S[1-9]\d*)\]/g, (marker, sourceId: string) => (
    valid.has(sourceId) ? marker : ''
  ))
  return sanitized.replace(/[ \t]+([，。！？；：,.!?;:])/g, '$1')
}
