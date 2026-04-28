/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { Compass, ZoomIn, ZoomOut, Rotate3D, Focus, X, Verified, FileText, MessageCircle } from 'lucide-react';
import { motion } from 'motion/react';

export default function GraphView() {
  const nodes = [
    { id: 1, label: 'NEUROPLASTICITY_INDEX', x: 500, y: 500, size: 12, type: 'variable', active: true },
    { id: 2, label: 'SYNAPTIC_DENSITY', x: 300, y: 400, size: 8, type: 'variable' },
    { id: 3, label: 'COGNITIVE_RESERVE', x: 700, y: 450, size: 10, type: 'variable' },
    { id: 4, label: 'CHEN ET AL. (2023)', x: 190, y: 540, size: 20, type: 'paper' },
    { id: 5, label: 'KIM ET AL. (2024)', x: 840, y: 340, size: 20, type: 'paper' },
    { id: 6, label: 'GARCIA (2022)', x: 510, y: 690, size: 20, type: 'paper' },
  ];

  const edges = [
    { from: 1, to: 2, dashed: true, color: '#14b8a6' },
    { from: 1, to: 3, color: '#f43f5e' },
    { from: 1, to: 6, color: '#14b8a6' },
    { from: 2, to: 4, weight: 0.5, color: '#94a3b8' },
    { from: 3, to: 5, weight: 1.5, color: '#8b5cf6' },
  ];

  return (
    <div className="flex-1 relative flex overflow-hidden bg-[#020617]">
      {/* Search Overlay */}
      <div className="absolute top-8 left-8 w-80 bg-surface-container-low/60 backdrop-blur-xl border border-outline-variant/30 rounded-2xl p-4 z-10 precision-shadow overflow-hidden">
        <div className="flex items-center gap-2 mb-4">
          <Compass className="w-4 h-4 text-secondary" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-outline">Node Finder</span>
        </div>
        <div className="space-y-3">
          <div className="p-3 bg-secondary/10 border border-secondary/20 rounded-xl cursor-not-allowed hover:bg-secondary/20 transition-all">
            <div className="text-xs font-bold text-on-secondary-container mb-1">Amyloid Beta Clearance</div>
            <div className="text-[10px] text-secondary/70 font-mono tracking-tight">8 connected papers • 3 variables</div>
          </div>
          <div className="p-3 bg-surface-container/10 border border-outline-variant/30 rounded-xl cursor-not-allowed hover:bg-surface-container/20 transition-all">
            <div className="text-xs font-bold text-on-surface-variant mb-1">Microglial Activation</div>
            <div className="text-[10px] text-outline font-mono tracking-tight">12 connected papers • 5 variables</div>
          </div>
        </div>
      </div>

      {/* Main Canvas Context Area */}
      <div className="flex-1 relative overflow-hidden">
        {/* SVG Graph Visualization */}
        <svg className="w-full h-full opacity-80" viewBox="0 0 1000 1000">
          <defs>
            <filter id="glow">
              <feGaussianBlur stdDeviation="3.5" result="coloredBlur"/>
              <feMerge>
                <feMergeNode in="coloredBlur"/>
                <feMergeNode in="SourceGraphic"/>
              </feMerge>
            </filter>
          </defs>
          
          {/* Grid lines */}
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#ffffff05" strokeWidth="1"/>
          </pattern>
          <rect width="1000" height="1000" fill="url(#grid)" />

          {/* Edges */}
          {edges.map((edge, i) => {
            const fromNode = nodes.find(n => n.id === edge.from)!;
            const toNode = nodes.find(n => n.id === edge.to)!;
            return (
              <line 
                key={i}
                x1={fromNode.x} y1={fromNode.y} 
                x2={toNode.x} y2={toNode.y} 
                stroke={edge.color} 
                strokeWidth={edge.weight || 1} 
                strokeDasharray={edge.dashed ? '4' : '0'} 
                className="opacity-40"
              />
            );
          })}

          {/* Nodes */}
          {nodes.map((node) => (
            <g key={node.id} className="cursor-pointer">
              {node.type === 'variable' ? (
                <circle 
                  cx={node.x} cy={node.y} r={node.size} 
                  fill={node.active ? '#14b8a6' : '#14b8a688'}
                  filter={node.active ? 'url(#glow)' : ''}
                  className="transition-all duration-300"
                />
              ) : (
                <rect 
                  x={node.x - 10} y={node.y - 10} 
                  width={20} height={20} 
                  fill="#475569" 
                  transform={`rotate(${node.x % 30} ${node.x} ${node.y})`}
                  className="opacity-60"
                />
              )}
              {/* Tooltip labels */}
              <text 
                x={node.x + 15} y={node.y + 5} 
                fill={node.active ? '#14b8a6' : '#94a3b8'} 
                fontSize="9" 
                className="font-mono tracking-widest font-bold uppercase opacity-80 pointer-events-none"
              >
                {node.label}
              </text>
            </g>
          ))}
        </svg>

        {/* Perspective Overlay Grids */}
        <div className="absolute inset-0 pointer-events-none opacity-10 bg-[radial-gradient(#1e293b_1px,transparent_1px)] [background-size:40px_40px]"></div>
      </div>

      {/* Detail Panel */}
      <aside className="absolute top-8 right-8 w-96 bottom-24 bg-surface-container-lowest/10 backdrop-blur-2xl border border-outline-variant/30 rounded-2xl flex flex-col z-20 overflow-hidden shadow-2xl">
        <div className="p-6 border-b border-outline-variant/30">
          <div className="flex items-center justify-between mb-4">
            <span className="px-2 py-0.5 bg-secondary-container/20 text-secondary text-[10px] font-mono font-bold rounded-md border border-secondary/40 uppercase tracking-widest">Variable Node</span>
            <button className="text-outline hover:text-on-surface transition-colors focus:outline-none">
              <X className="w-4 h-4" />
            </button>
          </div>
          <h2 className="text-2xl font-medium text-white mb-1 font-sans">Neuroplasticity Index (NI)</h2>
          <p className="text-outline text-xs leading-relaxed italic font-serif">"A composite metric representing the brain's structural and functional adaptability across lifelong learning cycles."</p>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-8 custom-scrollbar">
          <div>
            <h3 className="font-mono text-[10px] text-outline uppercase tracking-widest border-b border-outline-variant/10 pb-2 mb-4">Key Evidence Snippets</h3>
            <div className="space-y-4">
              <div className="p-4 bg-surface-container-low/20 border-l-2 border-secondary rounded-r-xl">
                <p className="font-serif text-on-primary-fixed-variant text-sm leading-relaxed italic mb-3">"...elevated NI levels were strongly correlated with increased synaptic pruning efficiency in the prefrontal cortex..."</p>
                <div className="flex items-center gap-2">
                  <Verified className="w-3.5 h-3.5 text-secondary" />
                  <span className="text-[10px] font-mono font-semibold text-outline">KIM ET AL. (2024), NATURE NEURO</span>
                </div>
              </div>
              <div className="p-4 bg-surface-container-low/20 border-l-2 border-outline rounded-r-xl">
                <p className="font-serif text-on-primary-fixed-variant text-sm leading-relaxed italic mb-3">"...suggesting NI as a non-linear predictor for cognitive decline onset in aging populations."</p>
                <div className="flex items-center gap-2">
                  <FileText className="w-3.5 h-3.5 text-outline" />
                  <span className="text-[10px] font-mono font-semibold text-outline">GARCIA (2022), BMJ</span>
                </div>
              </div>
            </div>
          </div>

          <div>
            <h3 className="font-mono text-[10px] text-outline uppercase tracking-widest border-b border-outline-variant/10 pb-2 mb-4">Downstream Effects</h3>
            <div className="flex flex-wrap gap-2">
              {['Long-term Potentiation', 'BDNF Expression', 'Dendritic Spines'].map((effect) => (
                <span key={effect} className="px-2.5 py-1.5 bg-surface-container-lowest/5 text-on-primary-fixed-variant text-[10px] font-semibold rounded-lg border border-outline-variant/30 hover:border-secondary transition-colors cursor-pointer capitalize">
                  {effect}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="p-6 bg-primary-container/90 border-t border-outline-variant/20">
          <button className="w-full bg-secondary hover:bg-secondary/90 text-white py-3 rounded-xl font-bold text-sm flex items-center justify-center gap-2 transition-all shadow-lg shadow-secondary/20 active:scale-[0.98]">
            <MessageCircle className="w-4 h-4" />
            Jump to Chat
          </button>
        </div>
      </aside>

      {/* Bottom Toolbar (Graph Controls) */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex items-center gap-4 p-2 bg-surface-container-low/80 backdrop-blur-xl border border-outline-variant/30 rounded-2xl z-30 shadow-[0_20px_50px_rgba(0,0,0,0.5)]">
        <div className="flex items-center border-r border-outline-variant/30 pr-4 mr-2 gap-1">
          <button className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-surface-container text-outline hover:text-on-surface transition-all active:scale-95">
            <ZoomIn className="w-5 h-5" />
          </button>
          <button className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-surface-container text-outline hover:text-on-surface transition-all active:scale-95">
            <ZoomOut className="w-5 h-5" />
          </button>
          <button className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-surface-container text-outline hover:text-on-surface transition-all active:scale-95">
            <Rotate3D className="w-5 h-5" />
          </button>
          <button className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-surface-container text-outline hover:text-on-surface transition-all active:scale-95">
            <Focus className="w-5 h-5" />
          </button>
        </div>
        <div className="flex items-center gap-8 px-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-[9px] font-mono text-outline uppercase tracking-widest font-bold">Max Hops</label>
            <input 
              type="range" 
              className="w-32 accent-secondary h-1.5 bg-surface-container rounded-full appearance-none cursor-pointer"
              defaultValue={3} 
              min={1} 
              max={10} 
            />
          </div>
          <div className="flex gap-6">
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-secondary shadow-[0_0_8px_#14b8a6]"></div>
              <span className="text-[10px] text-outline-variant font-mono font-bold uppercase tracking-tight">POSITIVE</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-rose-500 shadow-[0_0_8px_#f43f5e]"></div>
              <span className="text-[10px] text-outline-variant font-mono font-bold uppercase tracking-tight">NEGATIVE</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-violet-500 shadow-[0_0_8px_#8b5cf6]"></div>
              <span className="text-[10px] text-outline-variant font-mono font-bold uppercase tracking-tight">NON-LINEAR</span>
            </div>
          </div>
        </div>
        <button className="bg-surface-container hover:bg-surface-container-high text-on-surface px-5 py-2.5 rounded-xl font-mono text-[11px] font-bold tracking-widest transition-all border border-outline-variant/30 active:scale-[0.98]">
          EXPORT_GRAPH
        </button>
      </div>
    </div>
  );
}
