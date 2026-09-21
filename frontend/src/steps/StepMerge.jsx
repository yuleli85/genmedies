import { useState, useEffect, useRef } from 'react'
import toast from 'react-hot-toast'
import { mergeVideos, pollVideoTask, poll, uploadIntroImage, BASE_URL } from '../api'

export default function StepMerge({ videosData, scenesData, project, onDone, finalVideo }) {
  const [phase, setPhase] = useState('idle')
  const [message, setMessage] = useState('')
  const [useTTS, setUseTTS] = useState(true)
  const [narrations, setNarrations] = useState([])
  const [introImages, setIntroImages] = useState([])
  const introInputRef = useRef(null)

  const videos = videosData?.videos || []
  const scenes = scenesData?.scenes || []

  useEffect(() => {
    const texts = videos.map((v) => {
      const s = scenes.find((s) => s.scene_id === v.scene_id)
      return s?.narration || ''
    })
    setNarrations(texts)
  }, [videosData, scenesData])

  const updateNarration = (idx, value) =>
    setNarrations((prev) => prev.map((t, i) => i === idx ? value : t))

  const handleIntroUpload = async (e) => {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    for (const file of files) {
      try {
        const { data } = await uploadIntroImage(project, file)
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
    if (videos.length === 0) return toast.error('没有可合并的视频')
    setPhase('merging')
    setMessage(introImages.length ? '正在生成片头...' : useTTS ? '正在生成旁白配音并合并...' : '正在合并视频...')
    try {
      const video_paths = videos.map((v) => v.video_path)
      const intro_paths = introImages.map((i) => i.url)
      const { data: { task_id } } = await mergeVideos(
        project,
        video_paths,
        useTTS ? narrations : [],
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
      onDone(result.result)
      toast.success('视频合成完成！')
    } catch (e) {
      toast.error(`合并失败: ${e.message}`)
      setPhase('idle')
    }
  }

  return (
    <div className="step-panel">
      <h3 className="history-title">合并视频</h3>

      {/* 片头图片 */}
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
      </div>

      {/* TTS 旁白 */}
      <div className="merge-section">
        <label className="merge-label">
          <input type="checkbox" checked={useTTS} onChange={(e) => setUseTTS(e.target.checked)} />
          {' '}启用旁白配音
        </label>
        {useTTS && (
          <div className="narration-list">
            {videos.map((v, idx) => (
              <div key={v.scene_id} className="narration-item">
                <span className="narration-label">镜头 {v.scene_id}</span>
                <textarea
                  className="narration-text"
                  value={narrations[idx] || ''}
                  onChange={(e) => updateNarration(idx, e.target.value)}
                  rows={2}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 操作按钮 */}
      <div className="action-row">
        <button
          className="btn-primary"
          onClick={startMerge}
          disabled={phase === 'merging'}
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
      {finalVideo && (
        <div className="merge-result">
          <p className="merge-done-label">合成完毕</p>
          <video
            src={`${BASE_URL}${finalVideo.final_video_url}`}
            controls
            className="merge-preview-video"
          />
          <a
            href={`${BASE_URL}${finalVideo.final_video_url}`}
            download
            className="btn-primary"
            style={{ marginTop: 12 }}
          >
            下载视频
          </a>
        </div>
      )}
    </div>
  )
}
