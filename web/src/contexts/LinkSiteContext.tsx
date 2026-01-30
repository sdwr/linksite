'use client';

import React, { createContext, useContext } from 'react';
import { LinkSiteState } from '../types';

export interface LinkSiteContextType {
  state: LinkSiteState;
  isConnected: boolean;
  react: (targetId: string, value: 1 | -1) => Promise<void>;
  nominate: (targetId: string) => Promise<void>;
}

const LinkSiteContext = createContext<LinkSiteContextType | undefined>(undefined);

export const useLinkSite = () => {
  const context = useContext(LinkSiteContext);
  if (!context) {
    throw new Error('useLinkSite must be used within a LinkSiteProvider');
  }
  return context;
};

export const LinkSiteProvider = LinkSiteContext.Provider;
