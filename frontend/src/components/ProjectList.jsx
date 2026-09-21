import { useState, useEffect } from 'react'
import { listProjects, deleteProject, dramaCopyProject } from '../api'
import toast from 'react-hot-toast'

export default function ProjectList({ onNew, onResume, onPPT, onResumePPT, onDrama, onResumeDrama, onMd2Ppt, onPdf2Word, onVideoMerge, onScript2Video }) {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)

  const STEP_LABELS = ['', '上传形象', '上传文章', '拆分镜头', '生成视频', '合成完片']
  const PPT_PHASE_LABELS = {
    review: '编辑讲稿', tts: 'TTS 音频', animate: '幻灯片动画',
    merge: '合并视频', done: '已完成',
  }
  const DRAMA_PHASE_LABELS = {
    script: '剧本生成', shots: '分镜拆解', anchors: '角色锚点',
    keyframes: '关键帧', video: '图生视频', dub: '配音', merge: '合成', done: '已完成',
  }

  useEffect(() => {
    listProjects()
      .then(({ data }) => setProjects(data))
      .catch(() => setProjects([]))
      .finally(() => setLoading(false))
  }, [])

  const handleDelete = async (e, project_id) => {
    e.stopPropagation()
    await deleteProject(project_id)
    setProjects((prev) => prev.filter((p) => p.project_id !== project_id))
  }

  const handleCopyDrama = async (e, project_id) => {
    e.stopPropagation()
    try {
      const { data } = await dramaCopyProject(project_id)
      setProjects((prev) => [data, ...prev])
      toast.success('项目已复制')
    } catch {
      toast.error('复制失败')
    }
  }

  const formatDate = (iso) => {
    if (!iso) return ''
    return new Date(iso).toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' })
  }

  const videoProjects  = projects.filter(p => !p.type || p.type === 'video')
  const pptProjects    = projects.filter(p => p.type === 'ppt')
  const dramaProjects  = projects.filter(p => p.type === 'drama')

  return (
    <div className="project-list-page">
      <h2>AI 视频生成</h2>
      <p className="step-desc">选择历史项目继续，或创建新项目。</p>

      <div className="home-modes">
        <div className="mode-card" onClick={onNew}>
          <div className="mode-icon">📝</div>
          <h3>文章转视频</h3>
          <p>上传文章，AI 拆分镜头、生成配图和配音，合成完整视频</p>
          <button className="btn-primary">新建项目</button>
        </div>
        <div className="mode-card" onClick={onPPT}>
          <div className="mode-icon">📊</div>
          <h3>PPT 转视频</h3>
          <p>上传 PPTX，编辑每页讲稿，自动合成带配音的讲解视频</p>
          <button className="btn-primary">新建项目</button>
        </div>
        <div className="mode-card mode-card--drama" onClick={onDrama}>
          <div className="mode-icon">🎬</div>
          <h3>真人剧集</h3>
          <p>输入剧情梗概，AI 全自动生成剧本、分镜、配音，合成完整剧集</p>
          <button className="btn-primary">新建项目</button>
        </div>
        <div className="mode-card" onClick={onMd2Ppt}>
          <div className="mode-icon">📄</div>
          <h3>Markdown 转 PPT</h3>
          <p>上传 Markdown 文件，AI 智能拆分为幻灯片，生成专业 PPTX</p>
          <button className="btn-primary">开始转换</button>
        </div>
        <div className="mode-card" onClick={onPdf2Word}>
          <div className="mode-icon">📑</div>
          <h3>PDF 转 Word</h3>
          <p>上传 PDF，自动识别扫描页或图片中的文字，并写入可编辑 Word 文档</p>
          <button className="btn-primary">开始转换</button>
        </div>
        <div className="mode-card" onClick={onVideoMerge}>
          <div className="mode-icon">🎞️</div>
          <h3>合成视频</h3>
          <p>上传多个视频片段，添加片头和旁白，合并为完整视频</p>
          <button className="btn-primary">开始合成</button>
        </div>
        <div className="mode-card" onClick={onScript2Video}>
          <div className="mode-icon">🎬</div>
          <h3>脚本转视频</h3>
          <p>粘贴视频脚本文本，AI 自动解析分镜、生成配图配音，合成完整视频</p>
          <button className="btn-primary">开始生成</button>
        </div>
      </div>

      {loading && <p className="muted">加载中...</p>}

      {!loading && dramaProjects.length > 0 && (
        <>
          <h3 className="history-title">真人剧集</h3>
          <div className="project-cards">
            {dramaProjects.map((p) => (
              <div key={p.project_id} className="project-card" onClick={() => onResumeDrama?.(p.project_id)}>
                <div className="project-card-body">
                  <h3>{p.title || '未命名剧集'}</h3>
                  <span className="project-step">
                    进度：{DRAMA_PHASE_LABELS[p.phase] || p.phase || '剧本生成'}
                  </span>
                  {p.updated_at && <span className="project-date">{formatDate(p.updated_at)}</span>}
                </div>
                <button className="btn-secondary-sm" onClick={(e) => handleCopyDrama(e, p.project_id)}>复制</button>
                <button className="btn-danger-sm" onClick={(e) => handleDelete(e, p.project_id)}>删除</button>
              </div>
            ))}
          </div>
        </>
      )}

      {!loading && pptProjects.length > 0 && (
        <>
          <h3 className="history-title">PPT 项目</h3>
          <div className="project-cards">
            {pptProjects.map((p) => (
              <div key={p.project_id} className="project-card" onClick={() => onResumePPT(p.project_id)}>
                <div className="project-card-body">
                  <h3>{p.title || '未命名 PPT'}</h3>
                  <span className="project-step">
                    进度：{PPT_PHASE_LABELS[p.phase] || p.phase || '编辑讲稿'}
                  </span>
                  {p.updated_at && <span className="project-date">{formatDate(p.updated_at)}</span>}
                </div>
                <button className="btn-danger-sm" onClick={(e) => handleDelete(e, p.project_id)}>删除</button>
              </div>
            ))}
          </div>
        </>
      )}

      {!loading && videoProjects.length > 0 && (
        <>
          <h3 className="history-title">视频项目</h3>
          <div className="project-cards">
            {videoProjects.map((p) => (
              <div key={p.project_id} className="project-card" onClick={() => onResume(p.project_id)}>
                <div className="project-card-body">
                  <h3>{p.title || '未命名项目'}</h3>
                  <span className="project-step">进度：第 {p.step || 1} 步 · {STEP_LABELS[p.step] || ''}</span>
                  {p.updated_at && <span className="project-date">{formatDate(p.updated_at)}</span>}
                </div>
                <button className="btn-danger-sm" onClick={(e) => handleDelete(e, p.project_id)}>删除</button>
              </div>
            ))}
          </div>
        </>
      )}

      {!loading && projects.length === 0 && <p className="muted">暂无历史项目</p>}
    </div>
  )
}
