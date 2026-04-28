/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { PlusSquare, Bot, User, FileText, Send, Paperclip, Image as ImageIcon, Zap, Activity, CheckCircle, Clock } from 'lucide-react';
import { motion } from 'motion/react';

export default function ChatView() {
  const conversations = [
    { title: 'Syntactic structures in LLMs', time: '2 mins ago', active: true },
    { title: 'Agentic workflows for peer review', time: '4 hours ago', active: false },
    { title: 'Quantum entanglement protocols', time: 'Yesterday', active: false },
    { title: 'Transformer-based signal processing', time: 'Oct 12', active: false },
  ];

  const traceSteps = [
    { label: '1. Intent Classification', status: 'completed', desc: 'Routing to: Vector Search Engine' },
    { label: '2. Vector Search (Weaviate)', status: 'completed', desc: 'query: "neural network depth generalization", alpha: 0.75, limit: 5 chunks' },
    { label: '3. Extraction Phase', status: 'active', desc: 'Synthesizing paragraphs...' },
    { label: '4. Cross-Reference Validation', status: 'pending', desc: '' },
  ];

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Left: Conversation History */}
      <aside className="w-72 border-r border-outline-variant bg-surface-container-low flex flex-col">
        <div className="p-4 border-b border-outline-variant flex justify-between items-center group">
          <h2 className="text-[10px] font-bold text-on-surface uppercase tracking-widest font-mono">Conversations</h2>
          <button className="text-secondary hover:bg-secondary-container/20 p-1.5 rounded-lg transition-all">
            <PlusSquare className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {conversations.map((conv) => (
            <div 
              key={conv.title} 
              className={`p-3 rounded-xl transition-all cursor-pointer ${
                conv.active 
                ? 'bg-surface-container-lowest border border-outline-variant precision-shadow' 
                : 'hover:bg-surface-container border border-transparent'
              }`}
            >
              <p className={`text-sm font-medium truncate ${conv.active ? 'text-on-surface' : 'text-on-surface-variant'}`}>{conv.title}</p>
              <p className="text-[10px] text-outline font-mono mt-1 flex items-center gap-1.5">
                <Clock className="w-3 h-3" />
                {conv.time}
              </p>
            </div>
          ))}
        </div>
      </aside>

      {/* Center: Chat Interface */}
      <section className="flex-1 flex flex-col bg-surface-container-lowest relative overflow-hidden">
        <div className="flex-1 overflow-y-auto px-12 py-8 space-y-8">
          {/* User Message */}
          <div className="flex justify-end">
            <div className="max-w-[80%] bg-primary-container text-on-primary rounded-2xl rounded-tr-none px-6 py-4 shadow-lg border border-primary/10">
              <p className="leading-relaxed text-[15px]">
                Could you analyze the correlation between neural network depth and generalization error based on the 'ResNet' and 'DenseNet' foundational papers in my library?
              </p>
            </div>
          </div>

          {/* AI Message */}
          <div className="flex gap-4">
            <div className="w-8 h-8 rounded-lg bg-secondary-container/30 border border-secondary/20 flex items-center justify-center flex-shrink-0">
              <Bot className="w-5 h-5 text-secondary" />
            </div>
            <div className="max-w-[85%] space-y-4">
              <div className="font-serif text-[16px] text-on-surface leading-relaxed antialiased">
                The relationship between depth and generalization is central to both architectures. Based on your library, 
                He et al. (2015) demonstrate that residual connections allow for significantly deeper networks (up to 1001 layers) 
                without the degradation problem commonly seen in plain stacked layers 
                <span className="text-secondary font-mono text-[11px] font-bold bg-secondary-container/20 px-1.5 py-0.5 rounded-md ml-1 cursor-pointer hover:bg-secondary-container/40 transition-colors">[1]</span>. 
                In contrast, DenseNet architectures maintain a narrower layer width but maximize feature reuse through dense connections, 
                which often leads to better generalization with fewer parameters 
                <span className="text-secondary font-mono text-[11px] font-bold bg-secondary-container/20 px-1.5 py-0.5 rounded-md ml-1 cursor-pointer hover:bg-secondary-container/40 transition-colors">[2]</span>.
              </div>

              {/* Citations Grid */}
              <div className="grid grid-cols-2 gap-3 mt-4">
                {[
                  { ref: 'REF 1', title: 'Deep Residual Learning for Image Recognition', meta: 'He et al. (2015) · CVPR' },
                  { ref: 'REF 2', title: 'Densely Connected Convolutional Networks', meta: 'Huang et al. (2017) · CVPR' }
                ].map((cite) => (
                  <div key={cite.ref} className="bg-surface-container-low border border-outline-variant rounded-xl p-3 hover:border-secondary transition-all cursor-pointer group flex flex-col gap-1.5">
                    <div className="flex items-center gap-2">
                      <span className="text-[9px] font-mono font-bold bg-surface-container-lowest px-1.5 py-0.5 rounded text-outline border border-outline-variant">{cite.ref}</span>
                      <FileText className="w-3.5 h-3.5 text-outline group-hover:text-secondary transition-colors" />
                    </div>
                    <p className="text-[13px] font-semibold text-on-surface line-clamp-1 group-hover:text-secondary transition-colors">{cite.title}</p>
                    <p className="text-[10px] text-outline font-mono uppercase tracking-tight">{cite.meta}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* AI Status (Agent Mode) */}
          <div className="flex gap-4">
            <div className="w-8 h-8 rounded-lg bg-secondary-container/30 border border-secondary/20 flex items-center justify-center flex-shrink-0 animate-pulse-soft">
              <Bot className="w-5 h-5 text-secondary" />
            </div>
            <div className="bg-secondary-container/5 border border-secondary/10 rounded-xl px-4 py-3 flex items-center gap-3 animate-pulse-soft">
              <Activity className="w-4 h-4 text-secondary" />
              <span className="text-sm font-medium text-on-secondary-container">Synthesizing multi-modal datasets from recent arXiv submissions...</span>
            </div>
          </div>
        </div>

        {/* Search/Input Area */}
        <div className="p-8 border-t border-outline-variant bg-surface-container-lowest">
          <div className="max-w-4xl mx-auto space-y-4">
            {/* Mode Switcher */}
            <div className="flex items-center gap-1 p-1 bg-surface-container-low w-fit rounded-xl border border-outline-variant">
              <button className="px-5 py-2 text-xs font-bold rounded-lg bg-surface-container-lowest text-on-surface precision-shadow flex items-center gap-2 transition-all">
                <Zap className="w-4 h-4 fill-secondary text-secondary" />
                Fast (RAG)
              </button>
              <button className="px-5 py-2 text-xs font-bold text-outline hover:text-on-surface-variant flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Agent (Multi-step)
              </button>
            </div>

            {/* Input Box */}
            <div className="relative bg-surface-container-lowest border border-outline-variant rounded-2xl precision-shadow focus-within:ring-2 focus-within:ring-secondary/20 transition-all overflow-hidden">
              <textarea 
                className="w-full p-5 text-sm border-none focus:ring-0 resize-none font-sans min-h-[100px] outline-none"
                placeholder="Ask ScholarAI anything about your research..."
              ></textarea>
              <div className="flex items-center justify-between px-5 pb-4">
                <div className="flex items-center gap-2">
                  <button className="p-2 text-outline hover:text-secondary hover:bg-secondary-container/20 rounded-lg transition-all">
                    <Paperclip className="w-4 h-4" />
                  </button>
                  <button className="p-2 text-outline hover:text-secondary hover:bg-secondary-container/20 rounded-lg transition-all">
                    <ImageIcon className="w-4 h-4" />
                  </button>
                  <div className="h-4 w-px bg-outline-variant mx-2"></div>
                  <span className="text-[10px] font-mono text-outline uppercase tracking-widest">Context: Current Folder</span>
                </div>
                <button className="bg-secondary text-on-secondary px-6 py-2.5 rounded-xl text-xs font-bold hover:opacity-90 transition-all flex items-center gap-2 shadow-lg shadow-secondary/10">
                  Run Inference
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Right: Process Trace Sidebar */}
      <aside className="w-80 border-l border-outline-variant bg-surface-container-low flex flex-col">
        <div className="p-4 border-b border-outline-variant flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-secondary" />
            <h2 className="text-[10px] font-bold text-on-surface uppercase tracking-widest font-mono">Process Trace</h2>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <div className="relative pl-6 space-y-8 before:absolute before:left-[11px] before:top-2 before:bottom-2 before:w-[1px] before:bg-outline-variant">
            {traceSteps.map((step, idx) => (
              <div key={idx} className="relative">
                <span className={`absolute -left-[19px] top-1 w-2.5 h-2.5 rounded-full ring-4 ring-surface-container-low ${
                  step.status === 'completed' ? 'bg-outline-variant' : 
                  step.status === 'active' ? 'bg-secondary' : 'bg-outline-variant/30'
                }`}></span>
                <div className="space-y-1.5">
                  <p className={`text-[11px] font-bold uppercase tracking-tight ${step.status === 'active' ? 'text-secondary' : 'text-on-surface'}`}>
                    {step.label}
                  </p>
                  {step.desc && (
                    <div className={`p-2.5 rounded-lg text-[10px] font-mono leading-relaxed border transition-all ${
                      step.status === 'active' ? 'bg-secondary-container/30 border-secondary/20 text-on-secondary-container' : 'bg-surface-container-lowest border-outline-variant/50 text-on-surface-variant'
                    }`}>
                      {step.desc}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Token Usage Footer */}
        <div className="p-5 bg-surface-container-high/50 border-t border-outline-variant">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] font-bold uppercase tracking-widest text-outline">Tokens</span>
            <span className="text-[10px] font-mono font-bold text-on-surface">1.4k / 128k</span>
          </div>
          <div className="w-full bg-surface-container h-1.5 rounded-full overflow-hidden">
            <div className="bg-secondary h-full w-[12%]"></div>
          </div>
          <p className="text-[9px] text-outline mt-3 italic text-center font-mono">Model: Scholar-v4-Pro-70b</p>
        </div>
      </aside>
    </div>
  );
}
