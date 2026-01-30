import { LinkView } from '@/components/LinkView';
import { MockProvider } from '@/providers/MockProvider';
import { RealProvider } from '@/providers/RealProvider';

export default function Home() {
  const useRealBackend = process.env.NEXT_PUBLIC_USE_REAL_BACKEND === 'true';

  if (useRealBackend) {
    return (
      <RealProvider>
        <LinkView />
      </RealProvider>
    );
  }

  return (
    <MockProvider>
      <LinkView />
    </MockProvider>
  );
}
