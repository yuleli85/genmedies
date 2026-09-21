import { useState, useCallback } from 'react'
import { Toaster } from 'react-hot-toast'
import StepPortrait from './steps/StepPortrait'
import StepArticle from './steps/StepArticle'
import StepScenes from './steps/StepScenes'
import StepVideos from './steps/StepVideos'
import StepMerge from './steps/StepMerge'
import StepPPT from './steps/StepPPT'
import StepDrama from './steps/StepDrama'
import StepMd2Ppt from './steps/StepMd2Ppt'
import StepPdf2Word from './steps/StepPdf2Word'
import StepVideoMerge from './steps/StepVideoMerge'
import StepScript2Video from './steps/StepScript2Video'
import ProjectList from './components/ProjectList'
import { getProject, saveProject } from './api'
import './App.css'

const STEPS = [
  { id: 1, label: '上传形象' },
  { id: 2, label: '上传文章' },
  { id: 3, label: '拆分镜头' },
  { id: 4, label: '生成视频' },
  { id: 5, label: '合成完片' },
]

export default function App() {
  const [screen, setScreen] = useState('list') // 'list' | 'editor' | 'ppt' | 'drama' | 'md2ppt' | 'pdf2word' | 'videomerge' | 'script2video'
  const [step, setStep] = useState(1)
  const [project, setProject] = useState(null)
  const [pptProjectId, setPptProjectId] = useState(null)
  const [dramaProjectId, setDramaProjectId] = useState(null)

  const [portrait, setPortrait] = useState(null)
  const [article, setArticle] = useState(null)
  const [scenesData, setScenesData] = useState(null)
  const [imagesData, setImagesData] = useState(null)
  const [videosData, setVideosData] = useState(null)
  const [finalVideo, setFinalVideo] = useState(null)

  const persist = useCallback(async (projectId, patch) => {
    try {
      await saveProject(projectId, patch)
    } catch (e) {
      console.warn('保存项目状态失败', e)
    }
  }, [])

  const startNew = useCallback(() => {
    const id = `proj_${Date.now()}`
    setProject(id)
    setStep(1)
    setPortrait(null)
    setArticle(null)
    setScenesData(null)
    setImagesData(null)
    setVideosData(null)
    setFinalVideo(null)
    setScreen('editor')
  }, [])

  const resumeProject = useCallback(async (projectId) => {
    try {
      const { data } = await getProject(projectId)
      setProject(projectId)
      setPortrait(data.portrait || null)
      setArticle(data.article || null)
      setScenesData(data.scenesData || null)
      setImagesData(data.imagesData || null)
      setVideosData(data.videosData || null)
      setFinalVideo(data.finalVideo || null)
      setStep(data.step || 1)
      setScreen('editor')
    } catch (e) {
      console.error('加载项目失败', e)
    }
  }, [])

  const next = useCallback(() => setStep((s) => Math.min(s + 1, 5)), [])
  const goTo = useCallback((s) => setStep(s), [])

  if (screen === 'list') {
    return (
      <>
        <Toaster position="top-right" />
        <div className="app">
          <header className="header">
            <h1>GenVoid <span>AI 视频生成</span></h1>
          </header>
          <main className="content">
            <ProjectList
              onNew={startNew}
              onResume={resumeProject}
              onPPT={() => { setPptProjectId(null); setScreen('ppt') }}
              onResumePPT={(id) => { setPptProjectId(id); setScreen('ppt') }}
              onDrama={() => { setDramaProjectId(null); setScreen('drama') }}
              onResumeDrama={(id) => { setDramaProjectId(id); setScreen('drama') }}
              onMd2Ppt={() => setScreen('md2ppt')}
              onPdf2Word={() => setScreen('pdf2word')}
              onVideoMerge={() => setScreen('videomerge')}
              onScript2Video={() => setScreen('script2video')}
            />
          </main>
        </div>
      </>
    )
  }

  if (screen === 'drama') {
    return (
      <>
        <Toaster position="top-right" />
        <div className="app">
          <header className="header">
            <h1>GenVoid <span>AI 视频生成</span></h1>
          </header>
          <main className="content">
            <StepDrama
              onBack={() => setScreen('list')}
              initialProjectId={dramaProjectId}
            />
          </main>
        </div>
      </>
    )
  }

  if (screen === 'ppt') {
    return (
      <>
        <Toaster position="top-right" />
        <div className="app">
          <header className="header">
            <h1>GenVoid <span>AI 视频生成</span></h1>
          </header>
          <main className="content">
            <StepPPT
              onBack={() => setScreen('list')}
              initialProjectId={pptProjectId}
            />
          </main>
        </div>
      </>
    )
  }

  if (screen === 'md2ppt') {
    return (
      <>
        <Toaster position="top-right" />
        <div className="app">
          <header className="header">
            <h1>GenVoid <span>AI 视频生成</span></h1>
          </header>
          <main className="content">
            <StepMd2Ppt onBack={() => setScreen('list')} />
          </main>
        </div>
      </>
    )
  }

  if (screen === 'pdf2word') {
    return (
      <>
        <Toaster position="top-right" />
        <div className="app">
          <header className="header">
            <h1>GenVoid <span>AI 视频生成</span></h1>
          </header>
          <main className="content">
            <StepPdf2Word onBack={() => setScreen('list')} />
          </main>
        </div>
      </>
    )
  }

  if (screen === 'videomerge') {
    return (
      <>
        <Toaster position="top-right" />
        <div className="app">
          <header className="header">
            <h1>GenVoid <span>AI 视频生成</span></h1>
          </header>
          <main className="content">
            <StepVideoMerge onBack={() => setScreen('list')} />
          </main>
        </div>
      </>
    )
  }

  if (screen === 'script2video') {
    return (
      <>
        <Toaster position="top-right" />
        <div className="app">
          <header className="header">
            <h1>GenVoid <span>AI 视频生成</span></h1>
          </header>
          <main className="content">
            <StepScript2Video onBack={() => setScreen('list')} />
          </main>
        </div>
      </>
    )
  }

  return (
    <div className="app">
      <Toaster position="top-right" />
      <header className="header">
        <h1>GenVoid <span>AI 视频生成</span></h1>
        <button className="btn-ghost" onClick={() => setScreen('list')}>← 项目列表</button>
      </header>

      <nav className="stepper">
        {STEPS.map((s) => (
          <button
            key={s.id}
            className={`step-btn ${step === s.id ? 'active' : ''} ${step > s.id ? 'done' : ''}`}
            onClick={() => step > s.id && goTo(s.id)}
          >
            <span className="step-num">{step > s.id ? '✓' : s.id}</span>
            <span className="step-label">{s.label}</span>
          </button>
        ))}
      </nav>

      <main className="content">
        {step === 1 && (
          <StepPortrait
            onDone={(d) => {
              setPortrait(d)
              persist(project, { portrait: d, step: 2 })
              next()
            }}
          />
        )}
        {step === 2 && (
          <StepArticle
            onDone={(d) => {
              setArticle(d)
              persist(project, { article: d, step: 3 })
              next()
            }}
            portrait={portrait}
          />
        )}
        {step === 3 && (
          <StepScenes
            article={article}
            portrait={portrait}
            project={project}
            onDone={(d) => {
              setScenesData(d)
              setImagesData(d.images)
              persist(project, { scenesData: d, imagesData: d.images, step: 4, title: d.title || '' })
              next()
            }}
          />
        )}
        {step === 4 && (
          <StepVideos
            scenesData={scenesData}
            imagesData={imagesData}
            project={project}
            portrait={portrait}
            initialVideosData={videosData}
            onDone={(d) => {
              setVideosData(d)
              persist(project, { videosData: d, step: 5 })
              next()
            }}
          />
        )}
        {step === 5 && (
          <StepMerge
            videosData={videosData}
            scenesData={scenesData}
            project={project}
            onDone={(d) => {
              setFinalVideo(d)
              persist(project, { finalVideo: d, step: 5 })
            }}
            finalVideo={finalVideo}
          />
        )}
      </main>
    </div>
  )
}
