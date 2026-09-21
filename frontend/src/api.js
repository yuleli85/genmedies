import axios from 'axios'

// 优先用环境变量，否则跟随浏览器当前主机自动拼 8000 端口
export const BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  `${window.location.protocol}//${window.location.hostname}:8000`

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 300000,
})

// 统一处理网络错误，输出详细信息便于调试
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.code === 'ECONNABORTED') {
      err.message = `请求超时，请检查后端服务 (${BASE_URL})`
    } else if (!err.response) {
      err.message = `无法连接到后端 (${BASE_URL})，请检查服务是否运行`
    }
    return Promise.reject(err)
  }
)

export const uploadPortrait = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/api/upload/portrait', fd)
}

export const uploadArticle = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/api/upload/article', fd)
}

export const splitToScenes = (article_file_id, portrait_hint = '', force = false) =>
  api.post('/api/scenes/split', { article_file_id, portrait_hint, force })

export const pollSceneTask = (task_id) => api.get(`/api/scenes/task/${task_id}`)

export const listImageModels = () => api.get('/api/images/models')

export const generateImages = (project_id, scenes, portrait_description = '', force = false, model = 'hunyuan', prompt_lang = 'zh') =>
  api.post('/api/images/generate', { project_id, scenes, portrait_description, force, model, prompt_lang })

export const pollImageTask = (task_id) => api.get(`/api/images/task/${task_id}`)

export const generateVideos = (project_id, scenes, use_kling = true, existing_videos = [], total_scenes = 0, portrait_path = '', force = false) =>
  api.post('/api/videos/generate', { project_id, scenes, use_kling, existing_videos, total_scenes, portrait_path, force })

export const mergeVideos = (project_id, video_paths, narrations = [], intro_images = []) =>
  api.post('/api/videos/merge', { project_id, video_paths, narrations, intro_images })

export const pollVideoTask = (task_id) => api.get(`/api/videos/task/${task_id}`)

export const uploadSceneImage = (project_id, scene_id, file) => {
  const fd = new FormData()
  fd.append('project_id', project_id)
  fd.append('scene_id', scene_id)
  fd.append('file', file)
  return api.post('/api/upload/scene-image', fd)
}

export const uploadIntroImage = (project_id, file) => {
  const fd = new FormData()
  fd.append('project_id', project_id)
  fd.append('file', file)
  return api.post('/api/upload/intro-image', fd)
}

export const uploadVideo = (project_id, file) => {
  const fd = new FormData()
  fd.append('project_id', project_id)
  fd.append('file', file)
  return api.post('/api/upload/video', fd)
}

export const regenerateImage = (project_id, scene_id, image_prompt, portrait_description = '', model = 'hunyuan', prompt_lang = 'zh') =>
  api.post('/api/images/regenerate', { project_id, scene_id, image_prompt, portrait_description, model, prompt_lang })

export const uploadPPTX = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/api/ppt/upload', fd)
}

// 步进式 PPT 转视频 API
export const pptGenScripts = (file_id, slides) =>
  api.post('/api/ppt/gen-scripts', { file_id, slides })

export const pptGenScriptPage = (file_id, slide) =>
  api.post('/api/ppt/gen-script-page', { file_id, slide })

export const pptGenerateTTS = (file_id, pages, voice = 'zh-CN-XiaoxiaoNeural') =>
  api.post('/api/ppt/tts', { file_id, pages, voice })

export const pptRegenTTSPage = (file_id, page, script, voice = 'zh-CN-XiaoxiaoNeural') =>
  api.post('/api/ppt/tts-page', { file_id, page, script, voice })

export const pptAnimate = (file_id, pages, duration = 8) =>
  api.post('/api/ppt/animate', { file_id, pages, duration })

export const pptRegenAnimatePage = (file_id, page, duration = 8) =>
  api.post('/api/ppt/animate-page', { file_id, page, duration })

export const pptMerge = (file_id, pages) =>
  api.post('/api/ppt/merge', { file_id, pages })

export const pollPPTTask = (task_id) => api.get(`/api/ppt/task/${task_id}`)

export const getPPTStatus = (file_id) => api.get(`/api/ppt/status/${file_id}`)

export const listProjects = () => api.get('/api/projects')
export const getProject = (project_id) => api.get(`/api/projects/${project_id}`)
export const saveProject = (project_id, data) => api.post(`/api/projects/${project_id}`, data)
export const deleteProject = (project_id) => api.delete(`/api/projects/${project_id}`)

// PPT 项目（复用同一套存储，type='ppt' 区分）
export const savePPTProject = (project_id, data) =>
  api.post(`/api/projects/${project_id}`, { ...data, type: 'ppt' })
export const getPPTProject = (project_id) => api.get(`/api/projects/${project_id}`)

// ── Drama API ──────────────────────────────────────────────

export const dramaCreateProject = (data) =>
  api.post('/api/drama/project', data)

export const dramaGetProject = (project_id) =>
  api.get(`/api/drama/project/${project_id}`)

export const dramaUpdateProject = (project_id, data) =>
  api.post(`/api/drama/project/${project_id}`, data)

export const dramaUploadCharacterRef = (project_id, character_name, file) => {
  const fd = new FormData()
  fd.append('project_id', project_id)
  fd.append('character_name', character_name)
  fd.append('file', file)
  return api.post('/api/upload/character-ref', fd)
}

export const dramaCopyProject = (project_id) =>
  api.post(`/api/drama/project/${project_id}/copy`)

export const dramaGenScript = (project_id, episode = 1, force = false) =>
  api.post('/api/drama/script', { project_id, episode, force })

export const dramaGenShots = (project_id, episode, scenes, force = false) =>
  api.post('/api/drama/shots', { project_id, episode, scenes, force })

export const dramaGenKeyframes = (project_id, episode, shots, force_ids = [], provider = 'siliconflow') =>
  api.post('/api/drama/keyframes', { project_id, episode, shots, force_ids, provider })

export const dramaGenVideos = (project_id, episode, shots, force_ids = [], provider = 'local') =>
  api.post('/api/drama/videos', { project_id, episode, shots, force_ids, provider })

export const dramaGenDub = (project_id, episode, shots, voice_settings = {}, force_ids = []) =>
  api.post('/api/drama/dub', { project_id, episode, shots, voice_settings, force_ids })

export const dramaGenLipsync = (project_id, episode, shots, force_ids = []) =>
  api.post('/api/drama/lipsync', { project_id, episode, shots, force_ids })

export const dramaMerge = (project_id, episode, shots) =>
  api.post('/api/drama/merge', { project_id, episode, shots })

export const dramaClearCache = (project_id, scope = 'all') =>
  api.post('/api/drama/clear-cache', { project_id, scope })

export const pollDramaTask = (task_id) =>
  api.get(`/api/drama/task/${task_id}`)

// ── Markdown to PPT API ──────────────────────────────────

export const uploadMarkdown = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/api/md2ppt/upload', fd)
}

export const md2pptSplit = (file_id, content) =>
  api.post('/api/md2ppt/split', { file_id, content })

export const md2pptGenerate = (file_id, slides, original_filename = '') =>
  api.post('/api/md2ppt/generate', { file_id, slides, original_filename })

export const pollMd2PptTask = (task_id) =>
  api.get(`/api/md2ppt/task/${task_id}`)

export const uploadPdfToWord = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/api/pdf2word/upload', fd)
}

export const pdfToWordConvert = (file_id) =>
  api.post('/api/pdf2word/convert', { file_id })

export const pollPdfToWordTask = (task_id) =>
  api.get(`/api/pdf2word/task/${task_id}`)

// ── Script to Video API ──────────────────────────────────

export const scriptParse = (script_text) =>
  api.post('/api/script2video/parse', { script_text })

export const scriptGenImages = (project_id, scenes, characters = [], model = 'seedream') =>
  api.post('/api/script2video/generate', { project_id, scenes, characters, model })

export const scriptGenVideo = (project_id, scenes) =>
  api.post('/api/script2video/gen-video', { project_id, scenes })

export const pollScript2VideoTask = (task_id) =>
  api.get(`/api/script2video/task/${task_id}`)

export const uploadScriptImage = (project_id, scene_id, position, file) => {
  const fd = new FormData()
  fd.append('project_id', project_id)
  fd.append('scene_id', scene_id)
  fd.append('position', position)
  fd.append('file', file)
  return api.post('/api/upload/script-image', fd)
}

export const poll = async (fn, intervalMs = 3000, timeoutMs = 600000) => {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const { data } = await fn()
      if (data.status === 'done') return data
      if (data.status === 'error') {
        const err = new Error(data.message)
        err.partialResult = data.result  // 保留部分结果
        throw err
      }
    } catch (err) {
      // 任务不存在(404)或瞬时网络波动，继续等待
      if (err.response?.status === 404) {
        throw new Error('任务不存在，请重新提交')
      }
      if (!err.response) {
        // 真实网络断开才抛出
        throw err
      }
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  throw new Error('任务超时')
}
