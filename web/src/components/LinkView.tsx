'use client';

import React, { useState, useMemo } from 'react';
import { ChevronUp, ChevronDown, MessageSquare, Send } from 'lucide-react';
import { MOCK_NETWORK, LinkNode, Connection } from '@/data/mockData';
import { LinkCard } from './LinkCard';

export const LinkView: React.FC = () => {
  const [currentLinkId, setCurrentLinkId] = useState<string>('link-a');
  const currentNode = MOCK_NETWORK[currentLinkId];

  if (!currentNode) return <div className="text-white">Node not found</div>;

  // Helper to determine satellite positions
  // Helper to determine satellite positions
  const getPositionStyles = (pos: string): React.CSSProperties => {
    switch (pos) {
      case 'top': return { top: '5%', left: '50%', transform: 'translateX(-50%)' };
      case 'left': return { top: '5%', left: '5%' };
      case 'right': return { top: '5%', right: '5%' };
      default: return {};
    }
  };

  // Helper for SVG line coordinates (approximate centers based on screen %)
  const getLineCoordinates = (pos: string) => {
    // Center of screen is 50% 50%
    const center = { x: '50%', y: '50%' };
    let target = { x: '50%', y: '50%' };

    switch (pos) {
      case 'top': target = { x: '50%', y: '10%' }; break;
      case 'left': target = { x: '10%', y: '10%' }; break;
      case 'right': target = { x: '90%', y: '10%' }; break;
    }
    return { x1: center.x, y1: center.y, x2: target.x, y2: target.y };
  };

  return (
    <div className="relative w-full h-screen bg-[#050505] text-white overflow-hidden selection:bg-purple-500/30">

      {/* Background Ambient Glow */}
      <div className="absolute top-[-20%] left-[-20%] w-[50%] h-[50%] bg-purple-900/10 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-20%] w-[50%] h-[50%] bg-blue-900/10 blur-[120px] rounded-full pointer-events-none" />

      {/* SVG Tether Layer */}
      <svg className="absolute inset-0 w-full h-full pointer-events-none z-0">
        {currentNode.connections.map((conn) => {
          const coords = getLineCoordinates(conn.position);
          return (
            <line
              key={conn.targetId}
              x1={coords.x1}
              y1={coords.y1}
              x2={coords.x2}
              y2={coords.y2}
              stroke="rgba(255,255,255,0.1)"
              strokeWidth="2"
              strokeDasharray="5,5"
              className="animate-pulse"
            />
          );
        })}
      </svg>

      {/* Center Stage */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20 flex flex-col items-center">
        <LinkCard node={currentNode} />

        {/* The Underground (Comments) */}
        <div className="w-full mt-6 bg-neutral-900/80 backdrop-blur-md rounded-xl p-6 border border-white/5 animate-in fade-in slide-in-from-bottom-4 duration-700">
          <div className="flex items-center gap-2 mb-4 text-neutral-400">
            <MessageSquare size={16} />
            <span className="text-sm font-medium uppercase tracking-wider">Discussion</span>
          </div>
          <div className="space-y-3 max-h-[150px] overflow-y-auto pr-2 custom-scrollbar">
            {currentNode.comments.map((comment, idx) => (
              <div key={idx} className="text-sm group">
                <span className="font-bold text-purple-400 mr-2">{comment.user}</span>
                <span className="text-neutral-300 group-hover:text-white transition-colors">{comment.text}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 flex gap-2">
            <input
              type="text"
              placeholder="Add a comment..."
              className="flex-1 bg-black/50 border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-purple-500/50 transition-colors"
            />
            <button className="p-2 bg-white text-black rounded-lg hover:bg-neutral-200 transition-colors">
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* The Left Wing (Rating) */}
      <div className="absolute left-[calc(50%-550px)] top-1/2 -translate-y-1/2 flex flex-col items-center gap-4 z-30">
        <button className="p-3 rounded-full hover:bg-white/10 text-neutral-400 hover:text-green-400 transition-all hover:scale-110">
          <ChevronUp size={32} />
        </button>
        <div className="text-2xl font-bold font-mono tracking-tighter">
          {currentNode.stats.upvotes - currentNode.stats.downvotes}
        </div>
        <button className="p-3 rounded-full hover:bg-white/10 text-neutral-400 hover:text-red-400 transition-all hover:scale-110">
          <ChevronDown size={32} />
        </button>
      </div>

      {/* The Right Wing (Taxonomy) */}
      <div className="absolute right-[calc(50%-550px)] top-1/2 -translate-y-1/2 flex flex-col items-end gap-2 z-30">
        {currentNode.tags.map(tag => (
          <span key={tag} className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs font-medium text-neutral-300 hover:bg-white/10 hover:border-white/20 hover:scale-105 transition-all cursor-pointer">
            #{tag}
          </span>
        ))}
      </div>

      {/* The Constellation (Satellites) */}
      {currentNode.connections.map(conn => {
        const positionClasses = getPositionStyles(conn.position);
        const targetNode = MOCK_NETWORK[conn.targetId];
        if (!targetNode) return null;

        return (
          <div
            key={conn.targetId}
            className="absolute z-50 flex flex-col items-center gap-2 group cursor-pointer"
            style={getPositionStyles(conn.position)}
            onClick={() => setCurrentLinkId(conn.targetId)}
          >
            <div className="relative w-24 h-24 rounded-full border-2 border-white/10 group-hover:border-purple-500 transition-all duration-300 shadow-[0_0_15px_rgba(0,0,0,0.5)] group-hover:shadow-[0_0_25px_rgba(168,85,247,0.4)] overflow-hidden bg-black">
              <img src={targetNode.screenshot_url} alt={targetNode.title} className="w-full h-full object-cover opacity-60 group-hover:opacity-100 transition-opacity" />
              <div className="absolute inset-0 bg-black/40 group-hover:bg-transparent transition-colors" />
            </div>

            <div className="px-3 py-1 rounded-full bg-black/80 border border-white/10 backdrop-blur text-xs font-medium text-neutral-300 group-hover:text-white group-hover:border-purple-500/50 transition-all transform translate-y-0 group-hover:-translate-y-1 text-center whitespace-nowrap">
              {conn.label}
            </div>
            <div className="text-xs text-neutral-500 opacity-0 group-hover:opacity-100 transition-opacity absolute top-full mt-2 w-32 text-center pointer-events-none bg-black/80 px-2 py-1 rounded">
              {targetNode.title}
            </div>
          </div>
        )
      })}
    </div>
  );
};
