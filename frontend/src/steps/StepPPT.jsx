import { useState, useRef, useEffect } from 'react'
import toast from 'react-hot-toast'
import {
  uploadPPTX, pptGenScripts, pptGenScriptPage,
  pptGenerateTTS, pptRegenTTSPage,
  pptAnimate, pptRegenAnimatePage, pptMerge,
  pollPPTTask, poll, BASE_URL,
  savePPTProject, getPPTProject,
} from '../api'

const TTS_VOICES = [
  { value: 'zh-CN-YunjianNeural',  label: '云健（男·浑厚）' },
  { value: 'zh-CN-XiaoyiNeural',   label: '晓伊（女·活力）' },
  { value: 'zh-CN-XiaoxiaoNeural', label: '晓晓（女·温柔）' },
  { value: 'zh-CN-YunxiNeural',    label: '云希（男·活泼）' },
  { value: 'zh-CN-YunyangNeural',  label: '云扬（男·新闻）' },
]

// phase: upload | review | tts | animate | merge | done
export default function StepPPT({ onBack, initialProjectId = null }) {
  const [phase, setPhase]       = useState('upload')
  const [uploading, setUploading] = useState(false)
  const [fileInfo, setFileInfo] = useState(null)
  const [scripts, setScripts]   = useState([])
  const [genScriptLoading, setGenScriptLoading] = useState(false)
  const [regenScriptPage, setRegenScriptPage]   = useState(null)
  const [voice, setVoice]       = useState('zh-CN-YunjianNeural')
  const [pageStatus, setPageStatus] = useState({})
  const [message, setMessage]   = useState('')
  const [videoUrl, setVideoUrl] = useState('')
  const [stepError, setStepError] = useState('')
  const [running, setRunning]   = useState(false)
  const [projectId, setProjectId] = useState(initialProjectId)
  const [projectTitle, setProjectTitle] = useState('')
  const fileRef = useRef()

  // ── 恢复已保存项目 ────────────────────────────────────
  useEffect(() => {
    if (!initialProjectId) return
    getPPTProject(initialProjectId)
      .then(({ data }) => {
        if (!data.fileInfo) return
        setFileInfo(data.fileInfo)
        setScripts(data.scripts || [])
        setVoice(data.voice || 'zh-CN-YunjianNeural')
        setPageStatus(data.pageStatus || {})
        setVideoUrl(data.videoUrl || '')
        setProjectTitle(data.title || '')
        setPhase(data.phase || 'review')
        toast.success('项目已恢复')
      })
      .catch(() => toast.error('项目加载失败'))
  }, [initialProjectId])

  // ── 自动保存 ──────────────────────────────────────────
  const persist = (patch) => {
    const id = projectId || `ppt_${Date.now()}`
    if (!projectId) setProjectId(id)
    savePPTProject(id, {
      title: patch.title ?? projectTitle ?? fileInfo?.filename ?? '未命名 PPT',
      fileInfo,
      scripts,
      voice,
      pageStatus,
      videoUrl,
      phase,
      ...patch,
    }).catch(() => {})
    return id
  }

  // ── 工具 ──────────────────────────────────────────────

  const setPageField = (page, field, value) =>
    setPageStatus(prev => ({ ...prev, [page]: { ...prev[page], [field]: value } }))

  const pollTask = (taskId, onProgress) =>
    poll(
      async () => {
        const { data } = await pollPPTTask(taskId)
        if (data.status === 'running') onProgress?.(data)
        return { data }
      },
      3000, 1800000
    )

  // ── Step 1: 上传 ──────────────────────────────────────

  const handleUpload = async (file) => {
    if (!file) return
    setUploading(true)
    setMessage('正在上传并解析 PPT...')
    try {
      const { data } = await uploadPPTX(file)
      const initScripts = data.slides.map(s => ({
        page:   s.index,
        script: [s.title, s.text].filter(Boolean).join('\n').trim() || `第 ${s.index} 页`,
      }))
      setFileInfo(data)
      setScripts(initScripts)
      setPageStatus({})
      setPhase('review')
      // 新建项目并保存初始状态
      const id = `ppt_${Date.now()}`
      setProjectId(id)
      setProjectTitle(data.filename)
      savePPTProject(id, {
        title: data.filename,
        fileInfo: data,
        scripts: initScripts,
        voice,
        pageStatus: {},
        videoUrl: '',
        phase: 'review',
      }).catch(() => {})
      toast.success(`解析完成，共 ${data.slide_count} 页`)
    } catch (e) {
      toast.error(`上传失败: ${e.response?.data?.detail || e.message}`)
    } finally {
      setUploading(false)
    }
  }

  const updateScript = (idx, value) =>
    setScripts(prev => prev.map((s, i) => i === idx ? { ...s, script: value } : s))

  // ── AI 生成口播稿（全量） ─────────────────────────────
  const handleGenScripts = async () => {
    setGenScriptLoading(true)
    try {
      const { data } = await pptGenScripts(fileInfo.file_id, fileInfo.slides)
      const map = Object.fromEntries(data.scripts.map(s => [s.page, s.script]))
      setScripts(prev => prev.map(s => ({ ...s, script: map[s.page] ?? s.script })))
      toast.success('口播稿生成完成')
    } catch (e) {
      toast.error(`口播稿生成失败: ${e.response?.data?.detail || e.message}`)
    } finally {
      setGenScriptLoading(false)
    }
  }

  // ── AI 重新生成单页口播稿 ─────────────────────────────
  const handleRegenScript = async (item) => {
    const slide = fileInfo.slides.find(s => s.index === item.page)
    if (!slide) return
    setRegenScriptPage(item.page)
    try {
      const { data } = await pptGenScriptPage(fileInfo.file_id, slide)
      setScripts(prev => prev.map(s => s.page === item.page ? { ...s, script: data.script } : s))
      toast.success(`第 ${item.page} 页口播稿已重新生成`)
    } catch (e) {
      toast.error(`第 ${item.page} 页生成失败: ${e.response?.data?.detail || e.message}`)
    } finally {
      setRegenScriptPage(null)
    }
  }

  // ── Step 2→3: 生成 TTS ────────────────────────────────

  const handleTTS = async () => {
    setPhase('tts')
    setStepError('')
    setRunning(true)
    setMessage('正在生成 TTS 音频...')
    try {
      const { data: { task_id } } = await pptGenerateTTS(fileInfo.file_id, scripts, voice)
      const result = await pollTask(task_id, (data) => {
        setMessage(data.message || '生成中...')
        const pages = data.result?.pages || []
        pages.forEach(p => setPageField(p.page, 'tts', p.from_cache ? 'cached' : 'done'))
      })
      result.result.pages.forEach(p =>
        setPageField(p.page, 'tts', p.from_cache ? 'cached' : 'done')
      )
      setMessage('TTS 全部完成，可继续生成动画')
      persist({ phase: 'tts', scripts, voice })
      toast.success('TTS 全部完成')
    } catch (e) {
      // 部分页成功时保留已完成的状态
      const partial = e.partialResult?.pages || []
      partial.forEach(p => {
        if (!p.error) setPageField(p.page, 'tts', p.from_cache ? 'cached' : 'done')
      })
      setStepError(e.message)
      toast.error(`TTS 失败: ${e.message}`)
    } finally {
      setRunning(false)
    }
  }

  // ── Step 3→4: 生成动画 ────────────────────────────────

  const handleAnimate = async () => {
    setPhase('animate')
    setStepError('')
    setRunning(true)
    setMessage('正在生成幻灯片动画...')
    const pages = scripts.map(s => s.page)
    try {
      const { data: { task_id } } = await pptAnimate(fileInfo.file_id, pages)
      const result = await pollTask(task_id, (data) => {
        setMessage(data.message || '生成中...')
        const ps = data.result?.pages || []
        ps.forEach(p => setPageField(p.page, 'anim', p.from_cache ? 'cached' : 'done'))
      })
      result.result.pages.forEach(p =>
        setPageField(p.page, 'anim', p.from_cache ? 'cached' : 'done')
      )
      setMessage('动画全部完成，可继续合并视频')
      persist({ phase: 'animate' })
      toast.success('动画全部完成')
    } catch (e) {
      // 部分页成功时保留已完成的状态
      const partial = e.partialResult?.pages || []
      partial.forEach(p => {
        if (!p.error) setPageField(p.page, 'anim', p.from_cache ? 'cached' : 'done')
      })
      setStepError(e.message)
      toast.error(`动画生成失败: ${e.message}`)
    } finally {
      setRunning(false)
    }
  }

  // ── Step 4: 合并 ──────────────────────────────────────

  const handleMerge = async () => {
    setPhase('merge')
    setStepError('')
    setRunning(true)
    setMessage('正在混音并合并视频...')
    const pages = scripts.map(s => s.page)
    try {
      const { data: { task_id } } = await pptMerge(fileInfo.file_id, pages)
      const result = await pollTask(task_id, (data) => {
        setMessage(data.message || '合并中...')
        const ps = data.result?.pages || []
        ps.forEach(p => setPageField(p.page, 'mixed', 'done'))
      })
      setVideoUrl(result.result.video_url)
      setPhase('done')
      persist({ phase: 'done', videoUrl: result.result.video_url })
      toast.success('视频生成完毕！')
    } catch (e) {
      setStepError(e.message)
      toast.error(`合并失败: ${e.message}`)
    } finally {
      setRunning(false)
    }
  }

  // ── 单页重新生成 TTS ──────────────────────────────────

  const handleRegenTTS = async (item) => {
    setPageField(item.page, 'regenTts', 'loading')
    try {
      await pptRegenTTSPage(fileInfo.file_id, item.page, item.script, voice)
      setPageField(item.page, 'tts', 'done')
      setPageField(item.page, 'regenTts', null)
      toast.success(`第 ${item.page} 页音频已重新生成`)
    } catch (e) {
      toast.error(`第 ${item.page} 页 TTS 失败: ${e.response?.data?.detail || e.message}`)
      setPageField(item.page, 'regenTts', null)
    }
  }

  // ── 单页重新生成动画 ──────────────────────────────────

  const handleRegenAnim = async (page) => {
    setPageField(page, 'regenAnim', 'loading')
    try {
      await pptRegenAnimatePage(fileInfo.file_id, page)
      setPageField(page, 'anim', 'done')
      setPageField(page, 'regenAnim', null)
      toast.success(`第 ${page} 页动画已重新生成`)
    } catch (e) {
      toast.error(`第 ${page} 页动画失败: ${e.response?.data?.detail || e.message}`)
      setPageField(page, 'regenAnim', null)
    }
  }

  // ── 步骤指示器 ────────────────────────────────────────

  const STEPS = [
    { id: 'review',  label: '编辑讲稿' },
    { id: 'tts',     label: 'TTS 音频' },
    { id: 'animate', label: '幻灯片动画' },
    { id: 'merge',   label: '合并视频' },
    { id: 'done',    label: '完成' },
  ]
  const stepOrder = STEPS.map(s => s.id)
  const currentIdx = stepOrder.indexOf(phase)

  // ── 渲染 ──────────────────────────────────────────────

  return (
    <div className="step-panel ppt-panel">
      <div className="ppt-header">
        <h2>PPT 转视频</h2>
        <button className="btn-ghost" onClick={onBack}>← 返回首页</button>
      </div>

      {/* 上传区 */}
      {phase === 'upload' && (
        <div className="ppt-upload-zone" onClick={() => fileRef.current?.click()}>
          {uploading
            ? <><div className="spinner" /><p>{message}</p></>
            : <>
                <div className="ppt-upload-icon">📊</div>
                <p className="ppt-upload-hint">点击选择 .pptx 文件</p>
                <p className="ppt-upload-sub">支持 PowerPoint 2007+（.pptx）</p>
              </>
          }
          <input ref={fileRef} type="file" accept=".pptx,.ppt" hidden
            onChange={e => handleUpload(e.target.files[0])} />
        </div>
      )}

      {/* 步骤指示器（review 之后显示） */}
      {phase !== 'upload' && (
        <>
          <div className="ppt-file-info">
            <span>📊 {fileInfo?.filename}</span>
            <span>{fileInfo?.slide_count} 页</span>
          </div>

          <div className="ppt-stepper">
            {STEPS.map((s, i) => {
              const idx = stepOrder.indexOf(s.id)
              const state = idx < currentIdx ? 'done' : idx === currentIdx ? 'active' : 'pending'
              return (
                <div key={s.id} className={`ppt-step ${state}`}>
                  <span className="ppt-step-num">{state === 'done' ? '✓' : i + 1}</span>
                  <span className="ppt-step-label">{s.label}</span>
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* 编辑讲稿 */}
      {phase === 'review' && (
        <>
          <div className="ppt-voice-row" style={{ margin: '16px 0' }}>
            <label>配音语音</label>
            <select className="model-select" value={voice} onChange={e => setVoice(e.target.value)}>
              {TTS_VOICES.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
            </select>
          </div>

          <div className="ppt-scripts">
            {scripts.map((item, idx) => {
              const slide = fileInfo.slides.find(s => s.index === item.page)
              const regenLoading = regenScriptPage === item.page
              return (
                <div key={item.page} className="ppt-script-card">
                  <div className="ppt-script-head">
                    <span className="ppt-page-num">第 {item.page} 页</span>
                    {slide?.title && <span className="ppt-slide-title">{slide.title}</span>}
                    <button
                      className="btn-sm"
                      style={{ marginLeft: 'auto' }}
                      disabled={regenLoading || genScriptLoading}
                      onClick={() => handleRegenScript(item)}
                    >
                      {regenLoading ? 'AI 生成中...' : 'AI 重写'}
                    </button>
                  </div>
                  {slide?.image_url && (
                    <img
                      src={`${BASE_URL}${slide.image_url}`}
                      alt={`slide ${item.page}`}
                      className="ppt-slide-thumb"
                      onError={e => { e.target.style.display = 'none' }}
                    />
                  )}
                  <textarea
                    className="ppt-script-text"
                    value={item.script}
                    onChange={e => updateScript(idx, e.target.value)}
                    rows={4}
                    placeholder="输入这一页的口播讲稿..."
                  />
                </div>
              )
            })}
          </div>

          <div className="action-row" style={{ marginTop: 20 }}>
            <button className="btn-secondary" onClick={() => setPhase('upload')}>重新上传</button>
            <button className="btn-secondary" onClick={handleGenScripts} disabled={genScriptLoading || running}>
              {genScriptLoading ? 'AI 生成中...' : 'AI 生成全部口播稿'}
            </button>
            <button className="btn-primary" onClick={handleTTS} disabled={genScriptLoading}>开始生成 TTS</button>
          </div>
        </>
      )}

      {/* TTS / 动画 进度（逐页状态） */}
      {(phase === 'tts' || phase === 'animate') && (
        <>
          <p className="ppt-phase-msg">{message}</p>
          {stepError && <p className="ppt-error">{stepError}</p>}
          <div className="ppt-page-grid">
            {scripts.map(item => {
              const st = pageStatus[item.page] || {}
              const ttsState  = st.tts  || 'pending'
              const animState = st.anim || 'pending'
              return (
                <div key={item.page} className="ppt-page-card">
                  <span className="ppt-page-num">第 {item.page} 页</span>
                  <div className="ppt-page-badges">
                    <span className={`ppt-badge tts-${ttsState}`}>
                      {ttsState === 'done' ? '✓ 音频' : ttsState === 'cached' ? '⚡ 音频' : '… 音频'}
                    </span>
                    <span className={`ppt-badge anim-${animState}`}>
                      {animState === 'done' ? '✓ 动画' : animState === 'cached' ? '⚡ 动画' : '… 动画'}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
          <div className="action-row" style={{ marginTop: 16 }}>
            <button className="btn-secondary" onClick={() => setPhase('review')} disabled={running}>
              ← 返回编辑
            </button>
            {phase === 'tts' && (
              <>
                <button className="btn-secondary" onClick={handleTTS} disabled={running}>
                  {running ? '生成中...' : '重试 TTS'}
                </button>
                <button className="btn-primary" onClick={handleAnimate} disabled={running}>
                  下一步：生成动画 →
                </button>
              </>
            )}
            {phase === 'animate' && (
              <>
                <button className="btn-secondary" onClick={handleAnimate} disabled={running}>
                  {running ? '生成中...' : '重试动画'}
                </button>
                <button className="btn-primary" onClick={handleMerge} disabled={running}>
                  下一步：合并视频 →
                </button>
              </>
            )}
          </div>
        </>
      )}

      {/* 合并中 */}
      {phase === 'merge' && (
        <>
          <p className="ppt-phase-msg">{message}</p>
          {stepError && <p className="ppt-error">{stepError}</p>}
          <div className="ppt-page-grid">
            {scripts.map(item => {
              const mixedState = pageStatus[item.page]?.mixed || 'pending'
              return (
                <div key={item.page} className="ppt-page-card">
                  <span className="ppt-page-num">第 {item.page} 页</span>
                  <div className="ppt-page-badges">
                    <span className={`ppt-badge anim-${mixedState}`}>
                      {mixedState === 'done' ? '✓ 混音' : '… 混音'}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
          <div className="action-row" style={{ marginTop: 16 }}>
            <button className="btn-secondary" onClick={() => setPhase('animate')} disabled={running}>← 返回动画</button>
            <button className="btn-primary" onClick={handleMerge} disabled={running}>
              {running ? '合并中...' : '重试合并'}
            </button>
          </div>
        </>
      )}

      {/* 完成 — 视频预览 + 每页重新生成 */}
      {phase === 'done' && (
        <>
          <div className="ppt-done">
            <p className="ppt-done-label">视频生成完毕</p>
            <video src={`${BASE_URL}${videoUrl}`} controls className="ppt-preview-video" />
            <div className="action-row">
              <a href={`${BASE_URL}${videoUrl}`} download={projectTitle ? projectTitle.replace(/\.(pptx?|PPTX?)$/, '.mp4') : true} className="btn-primary">下载视频</a>
              <button className="btn-secondary" onClick={handleMerge}>重新合并</button>
            </div>
          </div>

          <h3 className="history-title" style={{ marginTop: 32 }}>单页重新生成</h3>
          <div className="ppt-regen-grid">
            {scripts.map(item => {
              const st = pageStatus[item.page] || {}
              const slide = fileInfo.slides.find(s => s.index === item.page)
              return (
                <div key={item.page} className="ppt-regen-card">
                  {slide?.image_url && (
                    <img src={`${BASE_URL}${slide.image_url}`} alt=""
                      className="ppt-regen-thumb"
                      onError={e => { e.target.style.display = 'none' }} />
                  )}
                  <div className="ppt-regen-body">
                    <span className="ppt-page-num">第 {item.page} 页</span>
                    <textarea
                      className="ppt-script-text"
                      value={item.script}
                      onChange={e => updateScript(scripts.indexOf(item), e.target.value)}
                      rows={3}
                    />
                    <div className="ppt-regen-actions">
                      <button
                        className="btn-sm"
                        disabled={st.regenTts === 'loading'}
                        onClick={() => handleRegenTTS(item)}
                      >
                        {st.regenTts === 'loading' ? '生成中...' : '重新生成音频'}
                      </button>
                      <button
                        className="btn-sm"
                        disabled={st.regenAnim === 'loading'}
                        onClick={() => handleRegenAnim(item.page)}
                      >
                        {st.regenAnim === 'loading' ? '生成中...' : '重新生成动画'}
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
