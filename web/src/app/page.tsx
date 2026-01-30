import { LinkView } from '@/components/LinkView';
import { MockProvider } from '@/providers/MockProvider';

export default function Home() {
  return (
    <MockProvider>
      <LinkView />
    </MockProvider>
  );
}
