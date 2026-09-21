import { useState, useRef } from 'react'
import toast from 'react-hot-toast'
import { scriptParse, scriptGenImages, scriptGenVideo, pollScript2VideoTask, poll, uploadScriptImage, BASE_URL } from '../api'

export default function StepScript2Video({ onBack }) {
  const [projectId] = useState(() => `s2v_${Date.now()}`)
  const [phase, setPhase] = useState('input')
  const [scriptText, setScriptText] = useState('')
  const [title, setTitle] = useState('')
  const [scenes, setScenes] = useState([])
  const [characters, setCharacters] = useState([])
  const [images, setImages] = useState([])
  const [parsing, setParsing] = useState(false)
  const [message, setMessage] = useState('')
  const [finalVideo, setFinalVideo] = useState(null)
  const fileInputRef = useRef(null)
  const [replaceTarget, setReplaceTarget] = useState(null)

  const handleParse = async () => {
    if (!scriptText.trim()) return toast.error('请输入脚本文本')
    setParsing(true)
    try {
      const { data } = await scriptParse(scriptText)
      setTitle(data.title || '')
      setScenes(data.scenes || [])
      setCharacters(data.characters || [])
      setPhase('review')
      toast.success(`解析完成，共 ${data.scenes?.length || 0} 个镜头`)
    } catch (e) {
      toast.error(`解析失败: ${e.response?.data?.detail || e.message}`)
    } finally {
      setParsing(false)
    }
  }

  const updateScene = (idx, field, value) =>
    setScenes((prev) => prev.map((s, i) => (i === idx ? { ...s, [field]: value } : s)))

  const removeScene = (idx) =>
    setScenes((prev) => prev.filter((_, i) => i !== idx).map((s, i) => ({ ...s, scene_id: i + 1 })))

  const handleGenImages = async () => {
    if (scenes.length === 0) return toast.error('没有分镜数据')
    setPhase('gen-images')
    setMessage('正在生成首尾帧图片...')
    try {
      const { data: { task_id } } = await scriptGenImages(projectId, scenes, characters)
      const result = await poll(
        async () => {
          const { data } = await pollScript2VideoTask(task_id)
          if (data.status === 'running') setMessage(data.message || '生成中...')
          return { data }
        },
        3000, 600000
      )
      setImages(result.result.images || [])
      setPhase('images')
      toast.success('图片生成完成，请确认或替换')
    } catch (e) {
      toast.error(`图片生成失败: ${e.message}`)
      setPhase('review')
    }
  }

  const handleReplaceImage = (sceneId, position) => {
    setReplaceTarget({ sceneId, position })
    fileInputRef.current?.click()
  }

  const onFileSelected = async (e) => {
    const file = e.target.files?.[0]
    if (!file || !replaceTarget) return
    try {
      const { data } = await uploadScriptImage(projectId, replaceTarget.sceneId, replaceTarget.position, file)
      setImages((prev) => prev.map((img) => {
        if (img.scene_id === replaceTarget.sceneId) {
          if (replaceTarget.position === 'start') {
            return { ...img, start_image: data.image_path, start_url: data.image_url }
          } else {
            return { ...img, end_image: data.image_path, end_url: data.image_url }
          }
        }
        return img
      }))
      toast.success('图片已替换')
    } catch (err) {
      toast.error('替换失败')
    }
    if (fileInputRef.current) fileInputRef.current.value = ''
    setReplaceTarget(null)
  }

  const handleGenVideo = async () => {
    setPhase('generating')
    setMessage('正在生成视频...')
    const videoScenes = scenes.map((s) => {
      const img = images.find((i) => i.scene_id === s.scene_id)
      return { ...s, start_image: img?.start_image || '', end_image: img?.end_image || '' }
    })
    try {
      const { data: { task_id } } = await scriptGenVideo(projectId, videoScenes)
      const result = await poll(
        async () => {
          const { data } = await pollScript2VideoTask(task_id)
          if (data.status === 'running') setMessage(data.message || '处理中...')
          return { data }
        },
        3000, 600000
      )
      setPhase('done')
      setFinalVideo(result.result)
      toast.success('视频生成完成！')
    } catch (e) {
      toast.error(`生成失败: ${e.message}`)
      setPhase('images')
    }
  }

  return (
    <div className="step-panel ppt-panel">
      <div className="ppt-header">
        <h2>脚本转视频</h2>
        <button className="btn-ghost" onClick={onBack}>← 返回首页</button>
      </div>

      <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={onFileSelected} />

      {phase === 'input' && (
        <div className="s2v-input">
          <label className="merge-label">粘贴视频脚本文本</label>
          <textarea
            className="s2v-textarea"
            value={scriptText}
            onChange={(e) => setScriptText(e.target.value)}
            rows={15}
            placeholder={"粘贴你的视频脚本，例如：\n\n镜头1（0-5秒）\n画面：办公室场景\n旁白：\"肩颈酸痛？只要5分钟...\""}
          />
          <div className="action-row" style={{ marginTop: 16 }}>
            <button className="btn-primary" onClick={handleParse} disabled={parsing}>
              {parsing ? 'AI 解析中...' : 'AI 解析分镜'}
            </button>
          </div>
        </div>
      )}

      {phase === 'review' && (
        <>
          <div className="s2v-title-row">
            <label className="merge-label">视频标题</label>
            <input className="s2v-title-input" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="s2v-scenes">
            {scenes.map((scene, idx) => (
              <div key={scene.scene_id} className="s2v-scene-card">
                <div className="s2v-scene-head">
                  <span className="ppt-page-num">镜头 {scene.scene_id}</span>
                  <span className="s2v-duration">{scene.duration} 秒</span>
                  <button className="intro-remove" onClick={() => removeScene(idx)}>×</button>
                </div>
                <div className="s2v-scene-fields">
                  <label>旁白</label>
                  <textarea value={scene.narration} onChange={(e) => updateScene(idx, 'narration', e.target.value)} rows={2} />
                  <label>画面描述</label>
                  <textarea value={scene.scene_desc} onChange={(e) => updateScene(idx, 'scene_desc', e.target.value)} rows={2} />
                  <label>首帧提示词</label>
                  <textarea value={scene.start_prompt} onChange={(e) => updateScene(idx, 'start_prompt', e.target.value)} rows={2} />
                  <label>尾帧提示词</label>
                  <textarea value={scene.end_prompt} onChange={(e) => updateScene(idx, 'end_prompt', e.target.value)} rows={2} />
                </div>
              </div>
            ))}
          </div>
          <div className="action-row" style={{ marginTop: 16 }}>
            <button className="btn-secondary" onClick={() => setPhase('input')}>← 重新输入</button>
            <button className="btn-primary" onClick={handleGenImages}>生成首尾帧图片</button>
          </div>
        </>
      )}

      {phase === 'gen-images' && (
        <div className="merge-progress" style={{ flexDirection: 'column', alignItems: 'center', padding: 40 }}>
          <div className="spinner" />
          <p style={{ marginTop: 16 }}>{message}</p>
        </div>
      )}

      {phase === 'images' && (
        <>
          <p className="merge-label" style={{ marginBottom: 12 }}>确认或替换每个镜头的首尾帧图片，然后生成视频</p>
          <div className="s2v-images-grid">
            {scenes.map((scene) => {
              const img = images.find((i) => i.scene_id === scene.scene_id)
              return (
                <div key={scene.scene_id} className="s2v-image-card">
                  <div className="s2v-image-head">
                    <span className="ppt-page-num">镜头 {scene.scene_id}</span>
                    <span className="s2v-duration">{scene.duration} 秒</span>
                  </div>
                  <div className="s2v-image-pair">
                    <div className="s2v-image-slot">
                      <span className="s2v-image-label">首帧</span>
                      {img?.start_url && <img src={`${BASE_URL}${img.start_url}`} alt="start" className="s2v-frame-img" />}
                      <button className="btn-sm" onClick={() => handleReplaceImage(scene.scene_id, 'start')}>替换</button>
                    </div>
                    <div className="s2v-image-slot">
                      <span className="s2v-image-label">尾帧</span>
                      {img?.end_url && <img src={`${BASE_URL}${img.end_url}`} alt="end" className="s2v-frame-img" />}
                      <button className="btn-sm" onClick={() => handleReplaceImage(scene.scene_id, 'end')}>替换</button>
                    </div>
                  </div>
                  <p className="s2v-narration-preview">{scene.narration}</p>
                </div>
              )
            })}
          </div>
          <div className="action-row" style={{ marginTop: 16 }}>
            <button className="btn-secondary" onClick={() => setPhase('review')}>← 返回编辑</button>
            <button className="btn-primary" onClick={handleGenVideo}>确认，生成视频</button>
          </div>
        </>
      )}

      {phase === 'generating' && (
        <div className="merge-progress" style={{ flexDirection: 'column', alignItems: 'center', padding: 40 }}>
          <div className="spinner" />
          <p style={{ marginTop: 16 }}>{message}</p>
        </div>
      )}

      {phase === 'done' && finalVideo && (
        <div className="merge-result">
          <p className="merge-done-label">视频生成完毕</p>
          <video src={`${BASE_URL}${finalVideo.final_video_url}`} controls className="merge-preview-video" />
          <div className="action-row" style={{ marginTop: 12 }}>
            <a href={`${BASE_URL}${finalVideo.final_video_url}`} download={title ? `${title}.mp4` : true} className="btn-primary">下载视频</a>
            <button className="btn-secondary" onClick={() => { setPhase('images'); setFinalVideo(null) }}>重新生成</button>
          </div>
        </div>
      )}
    </div>
  )
}
