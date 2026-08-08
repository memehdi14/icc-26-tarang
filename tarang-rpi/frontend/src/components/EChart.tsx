"use client";

import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";

interface EChartProps {
  option: EChartsOption;
  height?: string | number;
  className?: string;
}

export function EChart({ option, height = "100%", className = "" }: EChartProps) {
  return (
    <div style={{ height }} className={`w-full ${className}`}>
      <ReactECharts 
        option={option} 
        style={{ height: "100%", width: "100%" }} 
        opts={{ renderer: "canvas" }} 
      />
    </div>
  );
}
