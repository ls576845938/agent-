import {useLocation} from 'react-router-dom';
import LiveTradingDashboard from './LiveTradingDashboard';
import ResearchPortfolioWorkspace from './ResearchPortfolioWorkspace';
export default function ExecutionSafetyRoute() {
  const location = useLocation();
  return new URLSearchParams(location.search).get('view') === 'research-review'
    ? <ResearchPortfolioWorkspace key={location.search} surface="review" />
    : <LiveTradingDashboard />;
}
