import React from 'react';
import { ExternalLink } from 'lucide-react';
import { LinkNode } from '@/types';

interface LinkCardProps {
  node: LinkNode;
}

export const LinkCard: React.FC<LinkCardProps> = ({ node }) => {
  return (
    <div className="relative group w-[900px] max-w-[90vw] bg-neutral-900 rounded-2xl overflow-hidden shadow-2xl border border-white/10 hover:border-white/20 transition-all duration-500">
      {/* Image Container with 16:9 Aspect Ratio */}
      <div className="relative aspect-video w-full overflow-hidden">
        <img
          src={node.screenshot_url}
          alt={node.title}
          className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-105"
        />

        {/* Gradient Overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent opacity-80" />

        {/* Content Overlay */}
        <div className="absolute bottom-0 left-0 right-0 p-8 flex flex-col gap-4">
          <h1 className="text-4xl font-bold text-white tracking-tight leading-tight shadow-md">
            {node.title}
          </h1>

          <p className="text-neutral-300 text-lg line-clamp-2 max-w-xl">
            {node.description}
          </p>

          <a
            href={node.url}
            target="_blank"
            rel="noopener noreferrer"
            className="self-start mt-2 px-8 py-3 bg-white text-black font-semibold rounded-full flex items-center gap-2 hover:bg-neutral-200 transition-colors shadow-[0_0_20px_rgba(255,255,255,0.3)] hover:shadow-[0_0_30px_rgba(255,255,255,0.5)]"
          >
            Visit Link
            <ExternalLink size={18} />
          </a>
        </div>
      </div>

      {/* Glow Effect behind the card */}
      <div className="absolute -inset-1 bg-gradient-to-r from-blue-500 to-purple-500 rounded-2xl blur-xl opacity-20 -z-10 group-hover:opacity-40 transition-opacity duration-500" />
    </div>
  );
};
