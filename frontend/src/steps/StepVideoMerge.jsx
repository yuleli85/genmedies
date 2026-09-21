import { useState, useRef } from 'react'
import toast from 'react-hot-toast'
import { uploadVideo, uploadIntroImage, mergeVideos, pollVideoTask, poll, BASE_URL } from '../api'

export default function StepVideoMerge({ onBack }) {
  const [projectId] = useState(() => `merge_${Date.now()}`)
  const [videos, setVideos] = useState([])
  const [introImages, setIntroImages] = useState([])
  const [narration, setNarration] = useState('')
  const [phase, setPhase] = useState('idle')
  const [message, setMessage] = useState('')
  const [finalVideo, setFinalVideo] = useState(null)
  const [uploading, setUploading] = useState(false)

  const videoInputRef = useRef(null)
  const introInputRef = useRef(null)

  const handleVideoUpload = async (e) => {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    setUploading(true)
    for (const file of files) {
      try {
        const { data } = await uploadVideo(projectId, file)
        setVideos((prev) => [...prev, data])
      } catch (err) {
        toast.error(`上传失败: ${file.name}`)
      }
    }
    setUploading(false)
    if (videoInputRef.current) videoInputRef.current.value = ''
  }

  const removeVideo = (idx) =>
    setVideos((prev) => prev.filter((_, i) => i !== idx))

  const handleIntroUpload = async (e) => {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    for (const file of files) {
      try {
        const { data } = await uploadIntroImage(projectId, file)
        setIntroImages((prev) => [...prev, { url: data.image_url, name: file.name }])
      } catch (err) {
        toast.error(`上传失败: ${file.name}`)
      }
    }
    if (introInputRef.current) introInputRef.current.value = ''
  }

  const removeIntro = (idx) =>
    setIntroImages((prev) => prev.filter((_, i) => i !== idx))

  const startMerge = async () => {
    if (videos.length === 0) return toast.error('请先上传视频文件')
    setPhase('merging')
    setMessage(introImages.length ? '正在生成片头...' : '正在合并视频...')
    try {
      const video_paths = videos.map((v) => v.video_path)
      const intro_paths = introImages.map((i) => i.url)
      const { data: { task_id } } = await mergeVideos(
        projectId,
        video_paths,
        narration.trim() ? [narration] : [],
        intro_paths,
      )
      const result = await poll(
        async () => {
          const { data } = await pollVideoTask(task_id)
          if (data.status === 'running') setMessage(data.message || '处理中...')
          return { data }
        },
        3000, 600000
      )
      setPhase('done')
      setFinalVideo(result.result)
      toast.success('视频合成完成！')
    } catch (e) {
      toast.error(`合并失败: ${e.message}`)
      setPhase('idle')
    }
  }

  return (
    <div className="step-panel ppt-panel">
      <div className="ppt-header">
        <h2>合成视频</h2>
        <button className="btn-ghost" onClick={onBack}>← 返回首页</button>
      </div>

      {/* 上传视频 */}
      <div className="merge-section">
        <label className="merge-label">上传视频片段（保持原声）</label>
        <div className="video-upload-row">
          {videos.map((v, idx) => (
            <div key={idx} className="video-file-item">
              <span className="video-file-name">{v.filename}</span>
              <button className="intro-remove" onClick={() => removeVideo(idx)}>×</button>
            </div>
          ))}
          <button
            className="intro-add-btn"
            style={{ width: 'auto', padding: '0 16px' }}
            onClick={() => videoInputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? '上传中...' : '+ 添加视频'}
          </button>
          <input
            ref={videoInputRef}
            type="file"
            accept="video/*"
            multiple
            hidden
            onChange={handleVideoUpload}
          />
        </div>
      </div>

      {/* 片头图片 + 旁白 */}
      <div className="merge-section">
        <label className="merge-label">片头图片（可选，每张播放 4 秒）</label>
        <div className="intro-images-row">
          {introImages.map((img, idx) => (
            <div key={idx} className="intro-thumb-wrap">
              <img src={`${BASE_URL}${img.url}`} alt={img.name} className="intro-thumb" />
              <span className="intro-duration">4 秒</span>
              <button className="intro-remove" onClick={() => removeIntro(idx)}>×</button>
            </div>
          ))}
          <button className="intro-add-btn" onClick={() => introInputRef.current?.click()}>
            + 添加图片
          </button>
          <input
            ref={introInputRef}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={handleIntroUpload}
          />
        </div>
        {introImages.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <label className="merge-label">片头旁白文本（可选，将生成配音叠加到片头）</label>
            <textarea
              className="narration-text"
              value={narration}
              onChange={(e) => setNarration(e.target.value)}
              rows={3}
              placeholder="输入片头的旁白文本，留空则片头无配音..."
              style={{ width: '100%' }}
            />
          </div>
        )}
      </div>

      {/* 操作按钮 */}
      <div className="action-row">
        <button
          className="btn-primary"
          onClick={startMerge}
          disabled={phase === 'merging' || videos.length === 0}
        >
          {phase === 'merging' ? '合并中...' : '开始合并'}
        </button>
      </div>

      {/* 进度 */}
      {phase === 'merging' && (
        <div className="merge-progress">
          <div className="spinner" />
          <p>{message}</p>
        </div>
      )}

      {/* 最终视频 */}
      {phase === 'done' && finalVideo && (
        <div className="merge-result">
          <p className="merge-done-label">合成完毕</p>
          <video
            src={`${BASE_URL}${finalVideo.final_video_url}`}
            controls
            className="merge-preview-video"
          />
          <div className="action-row" style={{ marginTop: 12 }}>
            <a
              href={`${BASE_URL}${finalVideo.final_video_url}`}
              download
              className="btn-primary"
            >
              下载视频
            </a>
            <button className="btn-secondary" onClick={() => { setPhase('idle'); setFinalVideo(null) }}>
              重新合并
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
