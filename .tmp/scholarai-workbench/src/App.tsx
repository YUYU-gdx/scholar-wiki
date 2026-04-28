/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState } from 'react';
import { 
  Library, 
  Share2, 
  MessageSquare, 
  BookOpen, 
  Database, 
  Settings, 
  HelpCircle,
  Search,
  Zap,
  Bell,
  ChevronRight,
  Plus
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

// Sub-components
import LibraryView from './components/LibraryView';
import ChatView from './components/ChatView';
import GraphView from './components/GraphView';
import ReaderView from './components/ReaderView';
import PipelineView from './components/PipelineView';

type View = 'library' | 'graph' | 'chat' | 'reader' | 'pipeline';

export default function App() {
  const [currentView, setCurrentView] = useState<View>('library');

  const navItems = [
    { id: 'library', icon: Library, label: 'Library' },
    { id: 'graph', icon: Share2, label: 'Graph' },
    { id: 'chat', icon: MessageSquare, label: 'Chat' },
    { id: 'reader', icon: BookOpen, label: 'Reader' },
    { id: 'pipeline', icon: Database, label: 'Pipeline' },
  ];

  const collections = [
    'Deep Learning',
    'Cognitive Science',
    'Bioinformatics'
  ];

  const activeTags = ['#transformer', '#neuroscience'];

  return (
    <div className="flex h-screen bg-surface-container-low text-on-surface overflow-hidden font-sans">
      {/* Sidebar Navigation */}
      <aside className="w-64 border-r border-outline-variant bg-surface-container-lowest glass-shadow z-50 flex flex-col py-6 px-4 gap-2">
        <div className="mb-8 px-2 flex items-center gap-3">
          <div className="w-8 h-8 bg-primary-container text-on-primary-container rounded flex items-center justify-center">
            <Share2 className="w-4 h-4" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tighter text-on-surface leading-none">ScholarAI</h1>
            <p className="text-[10px] font-mono uppercase tracking-widest text-on-surface-variant mt-1">Workbench v2.4</p>
          </div>
        </div>

        <nav className="flex-1 flex flex-col gap-1">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setCurrentView(item.id as View)}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-200 text-[13px] font-medium tracking-tight ${
                currentView === item.id 
                ? 'text-secondary border-r-2 border-secondary bg-secondary-container/30' 
                : 'text-on-surface-variant hover:bg-surface-container'
              }`}
            >
              <item.icon className="w-5 h-5" />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        {/* Collections & Tags */}
        <div className="mt-8 px-2 space-y-6">
          <div>
            <span className="text-[10px] font-mono text-outline uppercase tracking-widest block mb-2">Collections</span>
            <ul className="space-y-1">
              {collections.map((coll) => (
                <li key={coll} className="flex items-center gap-2 text-[13px] text-on-surface-variant hover:text-secondary cursor-pointer transition-colors">
                  <span className="w-1 h-1 rounded-full bg-outline-variant"></span>
                  {coll}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <span className="text-[10px] font-mono text-outline uppercase tracking-widest block mb-2">Active Tags</span>
            <div className="flex flex-wrap gap-2">
              {activeTags.map((tag) => (
                <span key={tag} className="bg-secondary-container text-on-secondary-container px-2 py-0.5 rounded text-[10px] font-mono">
                  {tag}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-auto flex flex-col gap-1 border-t border-outline-variant pt-4">
          <button className="flex items-center gap-3 px-3 py-2 text-on-surface-variant hover:bg-surface-container rounded-lg text-[13px] font-medium transition-colors">
            <Settings className="w-5 h-5" />
            <span>Settings</span>
          </button>
          <button className="flex items-center gap-3 px-3 py-2 text-on-surface-variant hover:bg-surface-container rounded-lg text-[13px] font-medium transition-colors">
            <HelpCircle className="w-5 h-5" />
            <span>Support</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col relative overflow-hidden bg-background">
        {/* Top Header */}
        <header className="h-16 border-b border-outline-variant bg-surface-container-lowest/80 backdrop-blur-md flex justify-between items-center px-8 z-40">
          <div className="flex items-center flex-1 max-w-xl">
            <div className="relative w-full group">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-outline group-focus-within:text-secondary transition-colors" />
              <input 
                type="text" 
                placeholder="Query knowledge base..."
                className="w-full bg-surface-container border border-outline-variant rounded-lg px-10 py-2 text-sm font-mono focus:ring-1 focus:ring-secondary/30 outline-none transition-all placeholder:text-outline"
              />
            </div>
          </div>

          <div className="flex items-center gap-6">
            <div className="flex items-center gap-4">
              <button className="text-on-surface-variant hover:text-secondary transition-all flex items-center gap-1.5 focus:outline-none">
                <Zap className="w-5 h-5" />
                <span className="text-[11px] font-mono uppercase tracking-wider">Live Analysis</span>
              </button>
              <button className="text-on-surface-variant hover:text-secondary transition-all relative focus:outline-none">
                <Bell className="w-5 h-5" />
                <span className="absolute top-0 right-0 w-2 h-2 bg-error rounded-full border-2 border-surface-container-lowest"></span>
              </button>
            </div>
            <div className="h-8 w-px bg-outline-variant"></div>
            <div className="flex items-center gap-3">
              <div className="text-right">
                <p className="text-xs font-semibold text-on-surface leading-none">Dr. Aris Thorne</p>
                <p className="text-[10px] text-secondary font-mono">Lead Researcher</p>
              </div>
              <img 
                src="https://lh3.googleusercontent.com/aida-public/AB6AXuDxh4PstdOrt2xgXxc2z-W92ver-OppFwALe8bBRryKszGC0QWrWcn4XJu0xmPBKB1McaSECksoin4ybg-B4kTa_Qq1ItJstJVcVU8zsBAUk5eTDSghlGkNeWhgXHACJd0X8TfdesYp5jyZlVBS4vmx1tWQOZYDxqKsYLcAfZRt05CBDu01NprwkxjzKECmB7GVa08YH5zorMOmFMKWISx8s1Gw7rHOcHpqhUvsJnhaJ79epH1IFxyPsYBGMXJcnyYurwNrCrS9oA" 
                alt="Profile" 
                className="w-8 h-8 rounded-full border border-outline-variant object-cover"
              />
            </div>
          </div>
        </header>

        {/* View Transition Area */}
        <div className="flex-1 relative overflow-hidden">
          <AnimatePresence mode="wait">
            <motion.div
              key={currentView}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              className="absolute inset-0 flex"
            >
              {currentView === 'library' && <LibraryView />}
              {currentView === 'graph' && <GraphView />}
              {currentView === 'chat' && <ChatView />}
              {currentView === 'reader' && <ReaderView />}
              {currentView === 'pipeline' && <PipelineView />}
            </motion.div>
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}
