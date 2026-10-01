import {useLocation} from 'react-router-dom';
import PreviousResearchDashboard from './research/PreviousResearchDashboard';
import ResearchPortfolioWorkspace from './ResearchPortfolioWorkspace';
export default function ResearchDashboard() {
  const location = useLocation();
  const layout = new URLSearchParams(location.search).get('layout');
  if (layout === 'previous') return <><a className="research-return-new" href="/research">返回新版研究台</a><PreviousResearchDashboard /></>;
  if (layout === 'legacy') return <PreviousResearchDashboard />;
  const identity = new URLSearchParams(location.search);
  identity.delete('view');
  return <ResearchPortfolioWorkspace key={identity.toString()} surface="research" />;
}
