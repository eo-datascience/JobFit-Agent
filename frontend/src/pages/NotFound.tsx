import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="empty">
      <h1>That page does not exist</h1>
      <p className="muted" style={{ marginTop: '0.75rem' }}>
        It may have been a role from an earlier week. Roles change every Monday.{' '}
        <Link to="/roles">Browse this week's roles</Link>.
      </p>
    </div>
  )
}
