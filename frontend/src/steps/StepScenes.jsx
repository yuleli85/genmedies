import { useState, useRef, useEffect } from 'react'
import toast from 'react-hot-toast'
import {
  splitToScenes, pollSceneTask,
  generateImages, pollImageTask,
  regenerateImage, uploadSceneImage,
  listImageModels,
  poll, BASE_URL,
} from '../api'

export default function StepScenes({ article, portrait, project, onDone }) {
  const [phase, setPhase] = useState('idle') // idle | splitting | editing | generating | review | done
  const [scenes, setScenes] = useState([])
  const [images, setImages] = useState([])   // [{ scene_id, image_path, image_url }]
  const [title, setTitle] = useState('')
  const [message, setMessage] = useState('')
  const [regenState, setRegenState] = useState({})
  const [imageModels, setImageModels] = useState([{ id: 'hunyuan', name: '混元图像 3.0（腾讯）' }])
  const [selectedModel, setSelectedModel] = useState('hunyuan')
  const [promptLang, setPromptLang] = useState('zh')
  const fileInputRefs = useRef({})

  useEffect(() => {
    listImageModels().then(({ data }) => {
      setImageModels(data)
    }).catch(() => {})
  }, [])

  const startSplit = async (force = false) => {
    setPhase('splitting')
    setMessage(force ? '正在强制重新拆分...' : '正在拆分分镜...')
    try {
      const { data: { task_id } } = await splitToScenes(
        article.file_id,
        portrait ? `portrait file: ${portrait.filename}` : '',
        force
      )
      const result = await poll(
        async () => {
          const { data } = await pollSceneTask(task_id)
          return { data }
        },
        3000, 300000
      )
      setScenes(result.result.scenes)
      setTitle(result.result.title)
      setImages([])
      setPhase('editing')
      const hint = result.message === '命中缓存，直接返回' ? '（命中缓存）' : ''
      toast.success(`拆分完成，共 ${result.result.scenes.length} 个镜头 ${hint}`)
    } catch (e) {
      toast.error(`拆分失败: ${e.message}`)
      setPhase('idle')
    }
  }

  const updateScene = (idx, field, value) =>
    setScenes((prev) => prev.map((s, i) => i === idx ? { ...s, [field]: value } : s))

  const startGenImages = async (force = false) => {
    setPhase('generating')
    setMessage(force ? '正在强制重新生成图片（跳过缓存）...' : '正在生成分镜图片...')
    try {
      const { data: { task_id } } = await generateImages(project, scenes, portrait?.description || '', force, selectedModel, promptLang)
      const result = await poll(
        async () => {
          const { data } = await pollImageTask(task_id)
          if (data.status === 'running') setMessage(data.message || '正在生成图片...')
          return { data }
        },
        4000, 600000
      )
      const imgs = result.result.images
      setImages(imgs)
      setPhase('review')
      const cached = imgs.filter((i) => i.from_cache).length
      const hint = cached > 0 ? `（${cached} 张命中缓存，${imgs.length - cached} 张新生成）` : ''
      toast.success(`图片生成完毕 ${hint}，可编辑后继续`)
    } catch (e) {
      toast.error(`图片生成失败: ${e.message}`)
      setPhase('editing')
    }
  }

  const getImage = (scene_id) => images.find((i) => i.scene_id === scene_id)

  // 单张重新生成
  const handleRegen = async (scene) => {
    setRegenState((s) => ({ ...s, [scene.scene_id]: 'loading' }))
    try {
      const { data: { task_id } } = await regenerateImage(project, scene.scene_id, scene.image_prompt, portrait?.description || '', selectedModel, promptLang)
      const result = await poll(
        async () => { const { data } = await pollImageTask(task_id); return { data } },
        3000, 300000
      )
      const updated = result.result
      setImages((prev) => prev.map((i) => i.scene_id === scene.scene_id ? updated : i))
      toast.success(`镜头 ${scene.scene_id} 图片已更新`)
    } catch (e) {
      toast.error(`重新生成失败: ${e.message}`)
    } finally {
      setRegenState((s) => ({ ...s, [scene.scene_id]: 'idle' }))
    }
  }

  // 本地文件替换
  const handleFileReplace = async (scene, file) => {
    if (!file) return
    setRegenState((s) => ({ ...s, [scene.scene_id]: 'loading' }))
    try {
      const { data } = await uploadSceneImage(project, scene.scene_id, file)
      // 加时间戳参数强制刷新缓存
      setImages((prev) => prev.map((i) =>
        i.scene_id === scene.scene_id
          ? { ...data, image_url: data.image_url + '?t=' + Date.now() }
          : i
      ))
      toast.success(`镜头 ${scene.scene_id} 图片已替换`)
    } catch (e) {
      toast.error(`替换失败: ${e.message}`)
    } finally {
      setRegenState((s) => ({ ...s, [scene.scene_id]: 'idle' }))
    }
  }

  const confirmAndNext = () => {
    setPhase('done')
    onDone({ scenes, title, images })
  }

  return (
    <div className="step-panel">
      <h2>第三步：镜头拆分与图片生成</h2>
      <p className="step-desc">AI 将文章拆分为分镜脚本，并为每个镜头生成对应图片。</p>

      {phase === 'idle' && (
        <button className="btn-primary large" onClick={() => startSplit(false)}>开始 AI 拆分</button>
      )}

      {(phase === 'splitting' || phase === 'generating') && (
        <div className="progress-block">
          <div className="spinner" />
          <p>{message}</p>
        </div>
      )}

      {(phase === 'editing' || phase === 'review' || phase === 'done') && (
        <>
          {title && <h3 className="video-title">{title}</h3>}

          <div className="scenes-grid">
            {scenes.map((scene, idx) => {
              const img = getImage(scene.scene_id)
              const loading = regenState[scene.scene_id] === 'loading'
              return (
                <div key={scene.scene_id} className="scene-card">
                  <div className="scene-header">
                    <span className="scene-num">镜头 {scene.scene_id}</span>
                    <span className="scene-dur">{scene.duration}s</span>
                  </div>

                  {/* 图片预览区（review/done 阶段显示） */}
                  {(phase === 'review' || phase === 'done') && (
                    <div className="scene-img-wrap">
                      {loading ? (
                        <div className="scene-img-loading"><div className="spinner" /></div>
                      ) : img ? (
                        <img
                          src={`${BASE_URL}${img.image_url}`}
                          alt={`scene ${scene.scene_id}`}
                          className="scene-img"
                        />
                      ) : (
                        <div className="scene-img-empty">无图片</div>
                      )}
                      {/* 操作按钮 */}
                      {phase === 'review' && (
                        <div className="scene-img-actions">
                          <button
                            className="btn-sm"
                            disabled={loading}
                            onClick={() => handleRegen(scene)}
                          >重新生成</button>
                          <button
                            className="btn-sm"
                            disabled={loading}
                            onClick={() => fileInputRefs.current[scene.scene_id]?.click()}
                          >本地替换</button>
                          <input
                            type="file"
                            accept="image/*"
                            hidden
                            ref={(el) => { fileInputRefs.current[scene.scene_id] = el }}
                            onChange={(e) => handleFileReplace(scene, e.target.files[0])}
                          />
                        </div>
                      )}
                    </div>
                  )}

                  <textarea
                    className="scene-narration"
                    value={scene.narration}
                    onChange={(e) => updateScene(idx, 'narration', e.target.value)}
                    rows={2}
                  />
                  <div className="scene-prompt-block">
                    <label className="scene-prompt-label">图片提示词（需与旁白内容对应）</label>
                    <textarea
                      className="scene-prompt"
                      placeholder="描述旁白对应的具体画面内容（英文）"
                      value={scene.image_prompt}
                      onChange={(e) => updateScene(idx, 'image_prompt', e.target.value)}
                      rows={3}
                    />
                  </div>
                  <div className="scene-desc-row">
                    <span className="label">画面描述</span>
                    <span>{scene.scene_desc}</span>
                  </div>
                </div>
              )
            })}
          </div>

          {phase === 'editing' && (
            <div className="action-row">
              <button className="btn-secondary" onClick={() => startSplit(true)}>重新拆分（忽略缓存）</button>
              <select
                className="model-select"
                value={promptLang}
                onChange={(e) => setPromptLang(e.target.value)}
              >
                <option value="en">Prompt 英文</option>
                <option value="zh">Prompt 中文</option>
              </select>
              <select
                className="model-select"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
              >
                {imageModels.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
              <button className="btn-primary" onClick={() => startGenImages(false)}>生成分镜图片</button>
            </div>
          )}

          {phase === 'review' && (
            <div className="action-row">
              <button className="btn-secondary" onClick={() => startGenImages(true)}>全部重新生成（忽略缓存）</button>
              <button className="btn-primary" onClick={confirmAndNext}>确认，进入下一步</button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
