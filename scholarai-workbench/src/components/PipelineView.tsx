/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { CloudUpload, FileText, RefreshCw, Info, XCircle, CheckCircle, ChevronRight, Database, Zap, Activity, Terminal, ExternalLink } from 'lucide-react';
import { motion } from 'motion/react';

export default function PipelineView() {
  const stats = [
    { label: 'Papers Processing', value: '12', icon: FileText, trend: 'HEALTHY', color: 'text-secondary' },
    { label: 'Entities Extracted', value: '450', icon: Database, trend: '+12% vs yesterday', color: 'text-tertiary-container' },
    { label: 'Parser Accuracy', value: '98.4%', icon: Activity, trend: 'Avg 1.2s / page', color: 'text-secondary' },
    { label: 'Files Indexed', value: '3.4k', icon: CloudUpload, trend: '8.2 GB Total', color: 'text-on-surface-variant' },
  ];

  const activeJobs = [
    { id: 'JOB-8291-X', filename: 'neural_networks_2024.pdf', library: 'NEURO-AI', stage: 'Extract Entities', progress: 65, status: 'active' },
    { id: 'JOB-8295-A', filename: 'protein_folding_dynamics.pdf', library: 'BIO-CHEM', stage: 'Parse PDF', progress: 15, status: 'pending' },
    { id: 'JOB-8120-Q', filename: 'quantum_computing_foundations.pdf', library: 'PHYSICS-Q', stage: 'Finalize', progress: 100, status: 'completed' },
  ];

  const logs = [
    { time: '14:22:01.442', type: 'info', msg: 'Received SSE connection on /api/v2/stream' },
    { time: '14:22:01.890', type: 'event', msg: '{ "job_id": "JOB-8291-X", "stage": "entity_extraction", "provider": "gpt-4o" }' },
    { time: '14:22:05.112', type: 'data', msg: 'Extracting citation metadata from page 12 of 45...' },
    { time: '14:22:08.567', type: 'data', msg: 'Successfully identified 14 unique chemical compounds in Figure 3.' },
    { time: '14:22:12.330', type: 'event', msg: '{ "job_id": "JOB-8295-A", "stage": "pdf_parsing", "method": "vision_v4" }' },
    { time: '14:22:15.001', type: 'warn', msg: 'OCR quality low on page 4, fallback to intensive mode enabled.' },
    { time: '14:22:19.444', type: 'data', msg: 'Batch 45/102 processed. Memory usage: 1.4GB.' },
  ];

  return (
    <div className="flex-1 flex flex-col overflow-y-auto px-12 py-10 bg-surface-container-low/30 relative">
      {/* View Header */}
      <div className="flex justify-between items-end mb-10">
        <div className="space-y-1.5">
          <nav className="flex items-center gap-2 mb-3">
            <span className="text-[10px] font-mono font-bold text-outline uppercase tracking-widest">Workbench</span>
            <ChevronRight className="w-3 h-3 text-outline-variant" />
            <span className="text-[10px] font-mono font-bold text-secondary uppercase tracking-widest ">Pipeline Center</span>
          </nav>
          <h2 className="text-4xl font-bold tracking-tight text-on-surface font-sans">Data Pipeline</h2>
        </div>
        <button className="bg-secondary hover:bg-secondary/90 text-on-secondary flex items-center gap-2.5 px-6 py-3 rounded-xl shadow-lg shadow-secondary/20 transition-all hover:-translate-y-0.5 active:translate-y-0 active:scale-95">
          <CloudUpload className="w-5 h-5" />
          <span className="font-bold text-sm tracking-tight">Import Data</span>
        </button>
      </div>

      {/* Summary Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-10">
        {stats.map((stat) => (
          <div key={stat.label} className="bg-surface-container-lowest border border-outline-variant p-6 rounded-2xl glass-shadow flex flex-col justify-between group hover:border-secondary/30 transition-all hover:scale-[1.02] cursor-default">
            <div className="flex justify-between items-start">
              <div className={`p-2.5 rounded-xl bg-surface-container group-hover:bg-secondary/10 transition-colors`}>
                <stat.icon className={`w-5 h-5 ${stat.color} transition-colors group-hover:text-secondary`} />
              </div>
              <span className={`text-[10px] font-mono font-bold px-2 py-1 rounded-lg uppercase tracking-widest ${
                stat.trend.includes('HEALTHY') ? 'bg-secondary-container/20 text-secondary border border-secondary/10' : 'bg-surface-container text-on-surface-variant'
              }`}>
                {stat.trend}
              </span>
            </div>
            <div className="mt-5">
              <p className="text-3xl font-bold text-on-surface font-sans tracking-tight">{stat.value}</p>
              <p className="text-[10px] font-mono font-black text-outline uppercase tracking-widest mt-1.5">{stat.label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Job Status Table Section */}
      <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl overflow-hidden glass-shadow mb-10">
        <div className="px-6 py-4 border-b border-outline-variant flex justify-between items-center bg-surface-container-low/20">
          <h3 className="text-xs font-bold text-on-surface uppercase tracking-widest font-mono">Active Pipeline Jobs</h3>
          <div className="flex gap-2.5">
            <button className="p-2 hover:bg-surface-container rounded-lg transition-all text-outline">
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-low/10 text-[10px] font-mono font-black text-outline uppercase tracking-widest border-b border-outline-variant/10">
                <th className="px-6 py-5">Job ID</th>
                <th className="px-6 py-5">Filename</th>
                <th className="px-6 py-5">Library</th>
                <th className="px-6 py-5 text-center">Stage</th>
                <th className="px-6 py-5">Progress</th>
                <th className="px-6 py-5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/10">
              {activeJobs.map((job) => (
                <tr key={job.id} className="hover:bg-surface-container-low/10 transition-colors group">
                  <td className="px-6 py-5 font-mono text-[11px] font-bold text-on-surface-variant">{job.id}</td>
                  <td className="px-6 py-5">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center text-red-500 border border-red-100 group-hover:scale-110 transition-transform">
                        <FileText className="w-4 h-4" />
                      </div>
                      <span className="text-[14px] font-semibold text-on-surface">{job.filename}</span>
                    </div>
                  </td>
                  <td className="px-6 py-5">
                    <span className="bg-surface-container text-on-surface-variant text-[10px] font-mono font-bold px-2 py-1 rounded-lg border border-outline-variant/30 uppercase">
                      {job.library}
                    </span>
                  </td>
                  <td className="px-6 py-5 text-center">
                    <span className={`text-[10px] font-mono font-black uppercase px-3 py-1.5 rounded-full ${
                      job.status === 'completed' ? 'bg-secondary-container/20 text-secondary' : 'bg-surface-container text-outline-variant animate-pulse'
                    }`}>
                      {job.stage}
                    </span>
                  </td>
                  <td className="px-6 py-5 min-w-[200px]">
                    <div className="flex items-center gap-4">
                      <div className="flex-1 bg-surface-container h-1.5 rounded-full overflow-hidden">
                        <div 
                          className={`h-full transition-all duration-1000 ease-in-out ${job.status === 'completed' ? 'bg-secondary' : 'bg-secondary animate-pulse-soft'}`} 
                          style={{ width: `${job.progress}%` }}
                        ></div>
                      </div>
                      <span className="text-[11px] font-mono font-bold text-on-surface-variant">{job.progress}%</span>
                    </div>
                  </td>
                  <td className="px-6 py-5 text-right">
                    <div className="flex justify-end gap-3">
                      {job.status === 'completed' ? (
                        <>
                          <button className="text-secondary hover:scale-110 transition-transform"><CheckCircle className="w-5 h-5" /></button>
                          <button className="text-outline hover:text-secondary hover:scale-110 transition-all"><ExternalLink className="w-5 h-5" /></button>
                        </>
                      ) : (
                        <>
                          <button className="text-outline hover:text-secondary hover:scale-110 transition-all"><Info className="w-5 h-5" /></button>
                          <button className="text-outline hover:text-error hover:scale-110 transition-all"><XCircle className="w-5 h-5" /></button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Terminal Real-time Log View */}
      <div className="bg-primary-container rounded-2xl overflow-hidden glass-shadow border border-primary/20 mt-auto">
        <div className="px-6 py-3 border-b border-white/5 flex justify-between items-center bg-primary-container-variant/50">
          <div className="flex items-center gap-3">
            <Terminal className="w-4 h-4 text-secondary" />
            <h4 className="text-[10px] font-mono font-bold text-outline-variant uppercase tracking-widest">Real-time Pipeline Stream</h4>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-secondary animate-pulse shadow-[0_0_8px_#14b8a6]"></div>
              <span className="text-[10px] font-mono font-bold text-secondary tracking-widest">SSE CONNECTED</span>
            </div>
          </div>
        </div>
        <div className="p-8 font-mono text-[11px] text-on-primary-container bg-primary-container h-64 overflow-y-auto leading-relaxed selection:bg-secondary selection:text-white custom-scrollbar-dark">
          {logs.map((log, i) => (
            <div key={i} className="flex gap-6 mb-2.5 opacity-80 hover:opacity-100 transition-opacity">
              <span className="text-outline min-w-[90px]">{log.time}</span>
              <span className={`font-black min-w-[50px] uppercase ${
                log.type === 'info' ? 'text-secondary' : 
                log.type === 'event' ? 'text-on-tertiary-container' : 
                log.type === 'warn' ? 'text-amber-400' : 'text-blue-400'
              }`}>{log.type}:</span>
              <span className="tracking-tight">{log.msg}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Background Decorative Elements */}
      <div className="fixed top-0 right-0 -z-10 w-1/3 h-1/3 bg-gradient-to-br from-secondary/5 to-transparent blur-3xl rounded-full translate-x-1/2 -translate-y-1/2"></div>
      <div className="fixed bottom-0 left-64 -z-10 w-1/4 h-1/4 bg-gradient-to-tr from-tertiary-container/10 to-transparent blur-3xl rounded-full -translate-x-1/2 translate-y-1/2"></div>
    </div>
  );
}
