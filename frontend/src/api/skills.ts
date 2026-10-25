/** 作者：LHF；时间：2026-10-25；作用：文件系统技能管理、绑定及鉴权产物下载。 */
import request, { TOKEN_KEY } from './request'
import { storage } from '@/utils/storage'
import { saveDownload, type Capabilities, type SkillArtifact } from '@/chat-core/capabilities'

export interface SkillInfo {
  name: string; description?: string; enabled: boolean; valid?: boolean; error?: string
  body?: string; metadata?: Record<string, unknown>; hash?: string
  files?: Array<{ path: string; size: number }>; bound_agents?: string[]
}

/** 动态读取当前用户的全部本地技能。 */
export function listSkills(): Promise<SkillInfo[]> { return request.get('/v1/skills') }
/** 读取技能当前正文与资源清单。 */
export function getSkill(name: string): Promise<SkillInfo> { return request.get(`/v1/skills/${encodeURIComponent(name)}`) }
/** 预览文本资源，二进制资源返回标记。 */
export function readSkillFile(name: string, path: string): Promise<{ content?: string; binary: boolean }> {
  return request.get(`/v1/skills/${encodeURIComponent(name)}/files`, { params: { path } })
}
/** 上传或替换技能包，最终格式由服务端校验。 */
export function uploadSkill(file: File, replace?: string): Promise<SkillInfo> {
  const data = new FormData()
  data.append('file', file)
  const path = replace ? `/v1/skills/${encodeURIComponent(replace)}/package` : '/v1/skills'
  return replace ? request.put(path, data, { headers: { 'Content-Type': 'multipart/form-data' } })
    : request.post(path, data, { headers: { 'Content-Type': 'multipart/form-data' } })
}
/** 技能启停只写本地配置。 */
export function enableSkill(name: string, enabled: boolean): Promise<SkillInfo> { return request.put(`/v1/skills/${encodeURIComponent(name)}`, { enabled }) }
/** 删除前服务端检查 Agent 引用。 */
export function deleteSkill(name: string): Promise<void> { return request.delete(`/v1/skills/${encodeURIComponent(name)}`) }
/** 获取 Agent 的本地绑定，不读取技能数据库。 */
export function getAgentSkills(id: string): Promise<{ names: string[] }> { return request.get(`/v1/agents/${id}/skills`) }
/** 整体替换本地绑定。 */
export function bindAgentSkills(id: string, names: string[]): Promise<{ names: string[] }> { return request.put(`/v1/agents/${id}/skills`, { names }) }
/** @ 候选以当前 Agent 授权能力为准。 */
export function getCapabilities(id: string): Promise<Capabilities> { return request.get(`/v1/agents/${id}/capabilities`) }
/** 使用鉴权 fetch 下载附件，避免令牌出现在 URL 中。 */
export async function downloadArtifact(id: string, artifact: SkillArtifact): Promise<void> {
  const response = await fetch(`/api/v1/agents/${id}/skill-runs/${artifact.run_id}/artifacts?${new URLSearchParams({ path: artifact.path })}`, {
    headers: { Authorization: `Bearer ${storage.get<string>(TOKEN_KEY) || ''}` },
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.message || '产物不存在或已过期')
  }
  saveDownload(await response.blob(), artifact.name)
}
