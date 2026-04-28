/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { Filter, Sparkles, Plus, FileText, MoreVertical, Link2, BookOpen, X } from 'lucide-react';
import { motion } from 'motion/react';

export default function LibraryView() {
  const papers = [
    {
      id: 1,
      title: 'Attention Is All You Need',
      authors: 'Vaswani et al.',
      year: 2017,
      density: 88,
      variables: ['Self-Attention', '+2'],
      selected: true,
    },
    {
      id: 2,
      title: 'Deep Residual Learning for Image Recognition',
      authors: 'He et al.',
      year: 2016,
      density: 72,
      variables: ['ResNet', 'CNN'],
      selected: false,
    },
    {
      id: 3,
      title: 'Language Models are Few-Shot Learners',
      authors: 'Brown et al.',
      year: 2020,
      density: 94,
      variables: ['GPT-3', 'In-Context'],
      selected: false,
    },
    {
      id: 4,
      title: 'Adam: A Method for Stochastic Optimization',
      authors: 'Kingma & Ba',
      year: 2014,
      density: 65,
      variables: ['Optimizer', 'Gradient'],
      selected: false,
    },
  ];

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Central Table Section */}
      <section className="flex-1 overflow-auto px-8 py-6">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-medium tracking-tight text-on-surface font-sans">Research Library</h2>
            <span className="text-[10px] font-mono font-bold text-outline-variant bg-surface-container px-2 py-0.5 rounded">1,284 PAPERS</span>
          </div>
          <div className="flex items-center gap-2">
            <button className="flex items-center gap-2 px-3 py-1.5 border border-outline-variant rounded-lg text-xs font-medium hover:bg-surface-container transition-colors text-on-surface-variant">
              <Filter className="w-3.5 h-3.5" />
              Filter
            </button>
            <button className="flex items-center gap-2 px-3 py-1.5 bg-primary-container text-on-primary-fixed rounded-lg text-xs font-medium hover:opacity-90 transition-opacity">
              <Sparkles className="w-3.5 h-3.5" />
              Smart Sort
            </button>
            <button className="flex items-center gap-2 px-3 py-1.5 border border-secondary text-secondary rounded-lg text-xs font-medium hover:bg-secondary-container/20 transition-colors">
              <Plus className="w-3.5 h-3.5" />
              Import Paper
            </button>
          </div>
        </div>

        {/* Academic Table */}
        <div className="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden glass-shadow">
          <table className="w-full text-left border-collapse">
            <thead className="bg-surface-container-low border-b border-outline-variant">
              <tr>
                <th className="px-4 py-3 text-[11px] font-mono uppercase tracking-widest text-outline">Title</th>
                <th className="px-4 py-3 text-[11px] font-mono uppercase tracking-widest text-outline">Authors</th>
                <th className="px-4 py-3 text-[11px] font-mono uppercase tracking-widest text-outline">Year</th>
                <th className="px-4 py-3 text-[11px] font-mono uppercase tracking-widest text-outline">Density</th>
                <th className="px-4 py-3 text-[11px] font-mono uppercase tracking-widest text-outline">Core Variables</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant">
              {papers.map((paper) => (
                <tr 
                  key={paper.id} 
                  className={`group cursor-pointer transition-colors ${paper.selected ? 'bg-secondary-container/10' : 'hover:bg-surface-container-low'}`}
                >
                  <td className="px-4 py-4">
                    <div className="flex items-center gap-3">
                      <FileText className={`w-5 h-5 ${paper.selected ? 'text-secondary fill-secondary/20' : 'text-outline-variant'}`} />
                      <p className="font-medium text-on-surface text-sm line-clamp-1">{paper.title}</p>
                    </div>
                  </td>
                  <td className="px-4 py-4 text-xs text-on-surface-variant">{paper.authors}</td>
                  <td className="px-4 py-4 text-xs text-on-surface-variant">{paper.year}</td>
                  <td className="px-4 py-4">
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-1.5 bg-surface-container rounded-full overflow-hidden">
                        <div className="h-full bg-secondary" style={{ width: `${paper.density}%` }}></div>
                      </div>
                      <span className="text-[10px] font-mono font-bold text-secondary">{paper.density}%</span>
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <div className="flex gap-1">
                      {paper.variables.map((v) => (
                        <span key={v} className="px-1.5 py-0.5 bg-surface-container text-on-surface-variant text-[9px] font-mono uppercase rounded">
                          {v}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-4 text-right">
                    <button className="opacity-0 group-hover:opacity-100 transition-opacity">
                      <MoreVertical className="w-4 h-4 text-outline hover:text-secondary" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-6 flex items-center justify-between text-[11px] text-outline font-mono">
          <span>Showing 1-10 of 1,284 entries</span>
          <div className="flex gap-4">
            <button className="hover:text-secondary transition-colors">Previous</button>
            <button className="hover:text-secondary transition-colors">Next</button>
          </div>
        </div>
      </section>

      {/* AI Synopsis Panel */}
      <aside className="w-80 border-l border-outline-variant bg-surface-container-lowest flex flex-col p-6 overflow-y-auto">
        <div className="mb-6 flex justify-between items-start">
          <span className="bg-secondary-container/30 text-secondary px-2 py-1 rounded text-[10px] font-mono uppercase tracking-widest font-bold border border-secondary/20">AI Synopsis</span>
          <button className="text-outline hover:text-on-surface transition-colors focus:outline-none">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-6">
          <section>
            <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-2">Selected Subject</h3>
            <h4 className="text-lg font-medium text-on-surface leading-tight font-sans">Attention Is All You Need</h4>
            <p className="text-[13px] text-on-surface-variant mt-1 italic font-serif">NIPS, 2017</p>
          </section>

          <section className="bg-surface-container-low p-4 rounded-xl border border-outline-variant">
            <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-3">Quick Summary</h3>
            <p className="font-serif text-[14px] text-on-surface leading-relaxed">
              Proposes a new network architecture, the <span className="text-secondary font-semibold">Transformer</span>, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. Achieves state-of-the-art results on translation tasks while being more parallelizable.
            </p>
          </section>

          <section>
            <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-3">Key Variables</h3>
            <div className="space-y-2">
              {['Multi-Head Attention', 'Positional Encoding', 'Encoder-Decoder Stack'].map((v) => (
                <div key={v} className="p-2 border border-outline-variant rounded-lg bg-surface-container-lowest flex justify-between items-center group hover:border-secondary transition-all cursor-pointer shadow-sm">
                  <span className="text-[13px] font-medium text-on-surface">{v}</span>
                  <Link2 className="w-3.5 h-3.5 text-outline-variant group-hover:text-secondary transition-colors" />
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-3">Contextual Relevance</h3>
            <div className="relative pt-1">
              <div className="flex mb-2 items-center justify-between">
                <div>
                  <span className="text-[10px] font-mono uppercase inline-block py-1 px-2 rounded-full text-secondary bg-secondary-container/20 border border-secondary/10">
                    High Impact Cluster
                  </span>
                </div>
                <div className="text-right">
                  <span className="text-[10px] font-mono font-bold text-secondary">
                    98th Percentile
                  </span>
                </div>
              </div>
              <div className="overflow-hidden h-2 mb-4 flex rounded-full bg-surface-container">
                <div className="px-4 py-2 bg-secondary" style={{ width: '98%' }}></div>
              </div>
            </div>
          </section>

          <div className="pt-4 border-t border-outline-variant">
            <button className="w-full py-2.5 bg-primary-container text-on-primary-fixed rounded-lg text-sm font-semibold flex items-center justify-center gap-2 hover:opacity-90 transition-all shadow-md">
              <BookOpen className="w-4 h-4" />
              Open in Reader
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}
