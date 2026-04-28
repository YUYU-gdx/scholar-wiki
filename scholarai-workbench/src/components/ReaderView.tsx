/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { ZoomIn, ZoomOut, PenTool, Share2, Activity, Send, FileText, ChevronRight, Bot, MessageSquarePlus, Zap } from 'lucide-react';
import { motion } from 'motion/react';

export default function ReaderView() {
  const variables = [
    { name: 'Parameter Density', desc: 'Correlates with cross-domain reasoning.' },
    { name: 'RAG Reduction Rate', desc: 'Observed 42% decrease in hallucination.' },
  ];

  const annotations = [
    { text: 'Look up "product quantization" methods in current SOTA.', time: '2m ago', type: 'Methodology', color: 'bg-violet-400' },
    { text: 'Verify 42% reduction metric in Appendix B.', time: '15m ago', type: 'Validation', color: 'bg-secondary' },
  ];

  return (
    <div className="flex-1 flex overflow-hidden bg-surface-container-low">
      {/* PDF Reader Area */}
      <section className="flex-1 flex flex-col relative overflow-hidden">
        {/* Reader Toolbar */}
        <div className="h-12 bg-surface-container-lowest border-b border-outline-variant px-6 flex items-center justify-between z-30 precision-shadow">
          <div className="flex items-center gap-4">
            <span className="text-[11px] font-mono font-bold text-outline uppercase tracking-tight">p. 24 of 142</span>
            <div className="h-4 w-px bg-outline-variant"></div>
            <div className="flex items-center gap-2">
              <button className="p-1 hover:bg-surface-container rounded-md transition-colors text-outline">
                <ZoomOut className="w-4 h-4" />
              </button>
              <span className="text-[11px] font-mono font-bold text-on-surface">115%</span>
              <button className="p-1 hover:bg-surface-container rounded-md transition-colors text-outline">
                <ZoomIn className="w-4 h-4" />
              </button>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button className="flex items-center gap-2 px-3 py-1.5 border border-outline-variant rounded-lg text-[11px] font-mono font-bold uppercase tracking-wider text-on-surface-variant hover:border-secondary hover:text-secondary transition-all active:scale-95">
              <PenTool className="w-3.5 h-3.5" />
              Annotate
            </button>
            <button className="flex items-center gap-2 px-3 py-1.5 bg-primary-container text-secondary rounded-lg text-[11px] font-mono font-bold uppercase tracking-wider hover:opacity-90 transition-all shadow-md active:scale-95">
              <Share2 className="w-3.5 h-3.5" />
              Export to Graph
            </button>
          </div>
        </div>

        {/* Scrolling Document Area */}
        <div className="flex-1 overflow-y-auto p-12 flex justify-center bg-surface-container-low/30 scroll-smooth">
          <div className="max-w-[720px] w-full bg-surface-container-lowest precision-shadow px-16 py-20 border border-outline-variant min-h-[1400px] relative font-sans">
            {/* Page Header Headers */}
            <div className="absolute top-8 left-16 right-16 flex justify-between items-start opacity-30 pointer-events-none transition-opacity hover:opacity-100">
              <span className="text-[10px] font-mono tracking-widest uppercase font-bold text-outline">NEURAL_NETWORKS_REVIEW_2024.pdf</span>
              <span className="text-[10px] font-mono font-bold text-outline">SEC_4.2</span>
            </div>

            <article className="space-y-8">
              <h2 className="text-3xl font-medium text-on-surface mb-10 underline decoration-secondary/20 underline-offset-[12px] font-sans">
                4.2 Emergent Properties in Large-Scale Transformers
              </h2>
              
              <p className="font-serif text-[18px] text-on-surface leading-relaxed antialiased">
                The scaling laws observed in recent architectures suggest that <span className="bg-secondary-container/40 border-b-2 border-secondary/40 cursor-help transition-all hover:bg-secondary-container/60">parameter density correlates exponentially with cross-domain reasoning capability</span>. When evaluating the threshold for semantic coherence, we find that the transition is not linear. 
              </p>

              <div className="bg-surface-container-low/40 border-l-4 border-secondary p-8 my-10 rounded-r-xl group transition-all hover:bg-surface-container-low/60">
                <p className="font-serif italic text-lg text-on-surface-variant leading-relaxed opacity-80 group-hover:opacity-100 transition-opacity">
                  "The phenomenon of phase transition in model performance suggests an underlying structural complexity that remains partially opaque to traditional gradient descent analysis." 
                </p>
                <div className="mt-4 text-[11px] font-mono font-bold text-outline uppercase tracking-widest">— (Chen et al., 2023)</div>
              </div>

              <p className="font-serif text-[18px] text-on-surface leading-relaxed antialiased">
                Furthermore, the integration of <span className="bg-tertiary-container/20 border-b-2 border-on-tertiary-container/30 transition-all hover:bg-tertiary-container/40">retrieval-augmented generation (RAG)</span> layers within the core attention mechanism has shown a 42% reduction in hallucination rates during zero-shot prompts. This structural adaptation allows the model to treat internal weights as logic gates while external vectors serve as the persistent knowledge state.
              </p>

              <p className="font-serif text-[18px] text-on-surface leading-relaxed antialiased">
                One primary challenge remains the <span className="bg-secondary-container/40 border-b-2 border-secondary/40 cursor-help">computational overhead of k-dimensional vector lookups</span> in real-time inference. Optimization strategies such as product quantization (PQ) offer a reprieve, though at a slight cost to precision fidelity. 
              </p>

              {/* Figure Context Area */}
              <div className="w-full aspect-video bg-surface-container border border-outline-variant rounded-2xl my-12 relative overflow-hidden flex items-center justify-center group shadow-inner">
                <img 
                  className="absolute inset-0 w-full h-full object-cover opacity-20 grayscale transition-all duration-700 group-hover:scale-105 group-hover:opacity-30" 
                  src="https://lh3.googleusercontent.com/aida-public/AB6AXuB-SCXPWR1Q5wbhfEfROoSzT5HRX5Gr5ccltTLK9F0RmWgUTLGe4yUW06LRPNXD1z8Oq0WlT9zIHKDaZdmbm9wKo79pidhmvECbThe5D9y0MXatvVaN6qpW75EHDFEt09KLnHkqdzcSysJVgf05JxiqMr7rwYlltuRgJYCQlhVBaJxoqdD9qUbY0Lu83R7xsgKH7ET_BkZthv7f7fhHYKwgDQiSlqAJvXe05k87fhu7sAlLOffe5uifFDVqU-MWCmflttDmCEmfkA"
                  alt="Abstract Data Visualization"
                />
                <div className="relative z-10 text-center px-12 transform transition-transform group-hover:scale-110">
                  <Activity className="w-10 h-10 text-secondary mb-4 mx-auto drop-shadow-sm" />
                  <p className="text-[11px] font-mono font-bold text-outline uppercase tracking-[0.2em]">Fig 4.2: Vector Space Distribution Mapping</p>
                </div>
              </div>

              <p className="font-serif text-[18px] text-on-surface leading-relaxed antialiased">
                Preliminary results indicate that the quantization noise follows a Gaussian distribution, suggesting that error correction can be handled via auxiliary lightweight parity networks.
              </p>
            </article>
          </div>
        </div>
      </section>

      {/* Right AI Assistant Panel */}
      <aside className="w-96 border-l border-outline-variant bg-surface-container-lowest/80 backdrop-blur-xl flex flex-col z-40">
        <div className="p-8 border-b border-outline-variant">
          <div className="flex items-center gap-3 mb-1.5">
            <Activity className="w-5 h-5 text-secondary animate-pulse-soft" />
            <h3 className="text-sm font-bold tracking-tight text-on-surface uppercase font-sans">AI Research Assistant</h3>
          </div>
          <p className="text-[10px] text-outline font-mono font-bold uppercase tracking-widest pl-8">Analyzing Section 4.2 in real-time</p>
        </div>

        <div className="flex-1 overflow-y-auto p-8 space-y-10 custom-scrollbar">
          {/* Identified Variables */}
          <section>
            <h4 className="text-[10px] font-bold text-outline uppercase tracking-[0.2em] mb-5 flex items-center gap-2 border-b border-outline-variant/10 pb-2">
              <Zap className="w-3.5 h-3.5 text-secondary" />
              Identified Variables
            </h4>
            <div className="space-y-3">
              {variables.map((v) => (
                <div key={v.name} className="p-4 bg-surface-container-low/30 border border-outline-variant rounded-xl hover:border-secondary group transition-all cursor-pointer precision-shadow group">
                  <div className="flex justify-between items-center mb-1.5">
                    <span className="text-xs font-bold text-secondary font-mono uppercase tracking-tight">{v.name}</span>
                    <ChevronRight className="w-3.5 h-3.5 text-outline-variant group-hover:text-secondary group-hover:translate-x-1 transition-all" />
                  </div>
                  <p className="text-[11px] text-on-surface-variant leading-relaxed opacity-80">{v.desc}</p>
                </div>
              ))}
            </div>
          </section>

          {/* Proposed Relationships */}
          <section>
            <h4 className="text-[10px] font-bold text-outline uppercase tracking-[0.2em] mb-5 flex items-center gap-2 border-b border-outline-variant/10 pb-2">
              <Share2 className="w-3.5 h-3.5 text-secondary" />
              Proposed Relationships
            </h4>
            <div className="p-5 bg-secondary-container/10 border border-secondary/20 rounded-2xl relative overflow-hidden group hover:bg-secondary-container/20 transition-all">
              <div className="flex items-center gap-2.5 mb-4">
                <div className="w-2 h-2 rounded-full bg-secondary shadow-[0_0_8px_#14b8a6]"></div>
                <span className="text-[11px] font-bold font-mono text-on-secondary-container uppercase tracking-widest">Logic Inverse Link</span>
              </div>
              <div className="space-y-4">
                <div className="flex items-center justify-between text-[11px] px-2">
                  <span className="px-2 py-1 bg-surface-container-lowest border border-outline-variant/30 rounded-lg font-mono font-bold text-on-surface-variant">Quantization</span>
                  <Activity className="w-3.5 h-3.5 text-secondary opacity-50" />
                  <span className="px-2 py-1 bg-surface-container-lowest border border-outline-variant/30 rounded-lg font-mono font-bold text-on-surface-variant">Precision</span>
                </div>
                <p className="text-[11px] text-on-surface leading-relaxed italic opacity-80 border-t border-outline-variant/10 pt-3">
                  "Inference speed optimization presents a direct trade-off with semantic depth."
                </p>
              </div>
            </div>
          </section>

          {/* Summary Section */}
          <section>
            <h4 className="text-[10px] font-bold text-outline uppercase tracking-[0.2em] mb-5 flex items-center gap-2 border-b border-outline-variant/10 pb-2">
              <FileText className="w-3.5 h-3.5 text-secondary" />
              Summary Core
            </h4>
            <div className="p-5 bg-primary-container text-on-primary-fixed rounded-2xl shadow-xl border border-primary/20">
              <p className="text-[12px] leading-relaxed font-sans opacity-90 font-medium tracking-tight">
                The text argues for a non-linear scaling of AI reasoning. Key breakthrough: structural RAG integration acts as a persistent knowledge state. Main friction point: vector lookup overhead.
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                <span className="px-2.5 py-1 bg-secondary/20 text-secondary rounded-lg text-[9px] font-mono font-bold tracking-widest border border-secondary/20">SCALING_LAWS</span>
                <span className="px-2.5 py-1 bg-secondary/20 text-secondary rounded-lg text-[9px] font-mono font-bold tracking-widest border border-secondary/20">RAG_LAYERS</span>
              </div>
            </div>
          </section>

          {/* Annotations List */}
          <section>
            <h4 className="text-[10px] font-bold text-outline uppercase tracking-[0.2em] mb-5 pb-2 border-b border-outline-variant/10">My Annotations</h4>
            <div className="space-y-6">
              {annotations.map((ann, idx) => (
                <div key={idx} className="relative pl-5 border-l-2 border-outline-variant hover:border-secondary transition-colors group">
                  <div className={`absolute -left-[5px] top-1.5 w-2 h-2 rounded-full ${ann.color} shadow-sm group-hover:scale-125 transition-transform`}></div>
                  <p className="text-[13px] text-on-surface font-medium mb-1.5 leading-snug group-hover:text-on-surface transition-colors">{ann.text}</p>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-outline font-mono font-bold">{ann.time}</span>
                    <span className="w-1 h-1 bg-outline-variant/50 rounded-full"></span>
                    <span className={`text-[9px] font-mono font-black uppercase tracking-widest ${ann.type === 'Methodology' ? 'text-tertiary-container' : 'text-secondary'}`}>{ann.type}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* AI Prompt Input Bar */}
        <div className="p-6 border-t border-outline-variant bg-surface-container-lowest">
          <div className="relative flex items-center">
            <input 
              type="text" 
              className="w-full bg-surface-container-low border border-outline-variant rounded-xl pl-5 pr-12 py-3.5 text-xs font-mono focus:ring-1 focus:ring-secondary/30 outline-none transition-all placeholder:text-outline/50 shadow-inner" 
              placeholder="Ask AI about this page..." 
            />
            <button className="absolute right-3 p-1.5 text-secondary hover:scale-110 active:scale-95 transition-all focus:outline-none">
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Floating Action Button */}
      <motion.button 
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.95 }}
        className="fixed bottom-10 right-[420px] h-14 w-14 bg-surface-container-lowest rounded-full shadow-2xl border border-outline-variant flex items-center justify-center text-secondary hover:text-secondary-fixed transition-all z-50 group active:shadow-inner"
      >
        <MessageSquarePlus className="w-6 h-6 group-hover:rotate-12 transition-transform" />
      </motion.button>
    </div>
  );
}
