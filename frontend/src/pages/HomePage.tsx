import { motion } from 'motion/react'
import { GitBranch, Split, Bot, Sparkles, FolderTree, BookOpen } from 'lucide-react'
import { NavLink } from 'react-router-dom'

const features = [
  {
    Icon: GitBranch,
    title: 'Full Pipeline',
    desc: 'YAML dosyasından HTML çıktısına kadar tüm pipeline adımlarını çalıştır.',
    to: '/full',
  },
  {
    Icon: Split,
    title: 'Sub-Pipelines',
    desc: 'Pipeline adımlarını tek tek çalıştır: YAML → Question → Layout → HTML.',
    to: '/sub-pipelines',
  },
  {
    Icon: Bot,
    title: 'Standalone Agents',
    desc: 'Bireysel agentları bağımsız olarak test et ve sonuçları incele.',
    to: '/agents',
  },
  {
    Icon: FolderTree,
    title: 'Files & Favorites',
    desc: 'runs ve sp_files dosyalarını tree görünümünde aç, sil ve favorile.',
    to: '/files',
  },
  {
    Icon: BookOpen,
    title: 'Şablonlar',
    desc: 'Ders ve sınıf sekmelerine göre mock tema/alt başlık içeriklerini görüntüle.',
    to: '/templates',
  },
]

export function HomePage() {
  return (
    <div className="p-8 max-w-4xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        {/* Hero */}
        <div className="mb-12 text-center">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center shadow-xl mx-auto mb-4"
            style={{ background: 'linear-gradient(to bottom right, var(--primary), var(--secondary))' }}>
            <Sparkles className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-4xl mb-3" style={{ fontFamily: 'var(--font-display)' }}>
            Pipeline Dashboard
          </h1>
          <p className="text-muted-foreground text-lg max-w-md mx-auto">
            Sol menüden çalışma modunu seçerek pipeline ve agent run işlemlerini yönet.
          </p>
        </div>

        {/* Feature Cards */}
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-5">
          {features.map(({ Icon, title, desc, to }, i) => (
            <motion.div
              key={to}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.1 * (i + 1) }}
            >
              <NavLink
                to={to}
                className="block bg-card rounded-2xl shadow-lg border border-border p-6 hover:shadow-xl hover:-translate-y-1 transition-all duration-200 no-underline"
              >
                <div className="w-12 h-12 rounded-xl flex items-center justify-center mb-4"
                  style={{ background: 'linear-gradient(to bottom right, var(--accent), var(--muted))' }}>
                  <Icon className="w-6 h-6" style={{ color: 'var(--secondary)' }} />
                </div>
                <h2 className="text-lg font-medium mb-2 text-foreground" style={{ fontFamily: 'var(--font-display)' }}>
                  {title}
                </h2>
                <p className="text-sm text-muted-foreground">{desc}</p>
              </NavLink>
            </motion.div>
          ))}
        </div>

        {/* Info card */}
        <div className="mt-8 p-5 rounded-2xl border border-border bg-card">
          <p className="text-sm text-muted-foreground text-center">
            Sidebar'daki <strong className="text-foreground">Agent Mode</strong> göstergesi backend'in gerçek model mi yoksa stub modunda mı çalıştığını gösterir.
          </p>
        </div>
      </motion.div>
    </div>
  )
}
