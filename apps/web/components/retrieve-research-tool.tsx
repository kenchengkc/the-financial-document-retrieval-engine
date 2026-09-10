"use client";

import { FilingComparisonTool } from "./filing-comparison-tool";
import { FinancialFactsTool } from "./financial-facts-tool";
import { ResearchDatasetTool } from "./research-dataset-tool";

type ResearchTool = "compare" | "facts" | "dataset";

export function RetrieveResearchTool({ tool }: { tool: ResearchTool }) {
  if (tool === "compare") return <FilingComparisonTool />;
  if (tool === "facts") return <FinancialFactsTool />;
  return <ResearchDatasetTool />;
}
