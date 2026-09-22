import { Route, Routes, useLocation } from 'react-router-dom'
import { useEffect } from 'react'
import Layout from './components/Layout'
import Gate from './components/Gate'
import Overview from './pages/Overview'
import Roles from './pages/Roles'
import RoleDetail from './pages/RoleDetail'
import Skills from './pages/Skills'
import HowItWorks from './pages/HowItWorks'
import NotFound from './pages/NotFound'

const TITLES: Record<string, string> = {
  '/': 'This week',
  '/roles': 'Roles',
  '/skills': 'Skills',
  '/how-it-works': 'How it works',
}

function ScrollAndTitle() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
    const title = TITLES[pathname] ?? (pathname.startsWith('/roles/') ? 'Role' : 'Not found')
    document.title = `${title} | JobFit Agent`
  }, [pathname])
  return null
}

export default function App() {
  return (
    <>
      <ScrollAndTitle />
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Gate><Overview /></Gate>} />
          <Route path="roles" element={<Gate><Roles /></Gate>} />
          <Route path="roles/:id" element={<Gate><RoleDetail /></Gate>} />
          <Route path="skills" element={<Gate><Skills /></Gate>} />
          <Route path="how-it-works" element={<HowItWorks />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </>
  )
}
