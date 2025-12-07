/**
 * Chart Export Utilities
 * Provides functionality to export charts as PNG/PDF and data as CSV/JSON
 */

import html2canvas from 'html2canvas';
import jsPDF from 'jspdf';

export interface ExportOptions {
  filename?: string;
  format: 'png' | 'pdf' | 'csv' | 'json';
  quality?: number;
}

/**
 * Export a chart element as PNG
 */
export const exportChartAsPNG = async (
  chartElement: HTMLElement,
  filename: string = 'chart'
): Promise<void> => {
  try {
    const canvas = await html2canvas(chartElement, {
      scale: 2,
      backgroundColor: '#ffffff',
      logging: false
    });

    const link = document.createElement('a');
    link.download = `${filename}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  } catch (error) {
    console.error('Error exporting chart as PNG:', error);
    throw new Error('Failed to export chart as PNG');
  }
};

/**
 * Export a chart element as PDF
 */
export const exportChartAsPDF = async (
  chartElement: HTMLElement,
  filename: string = 'chart'
): Promise<void> => {
  try {
    const canvas = await html2canvas(chartElement, {
      scale: 2,
      backgroundColor: '#ffffff',
      logging: false
    });

    const imgData = canvas.toDataURL('image/png');
    const pdf = new jsPDF({
      orientation: canvas.width > canvas.height ? 'landscape' : 'portrait',
      unit: 'px',
      format: [canvas.width, canvas.height]
    });

    pdf.addImage(imgData, 'PNG', 0, 0, canvas.width, canvas.height);
    pdf.save(`${filename}.pdf`);
  } catch (error) {
    console.error('Error exporting chart as PDF:', error);
    throw new Error('Failed to export chart as PDF');
  }
};

/**
 * Export data as CSV
 */
export const exportDataAsCSV = (
  data: Array<Record<string, any>>,
  filename: string = 'data'
): void => {
  try {
    if (!data || data.length === 0) {
      throw new Error('No data to export');
    }

    // Get headers from first object
    const headers = Object.keys(data[0]);
    
    // Create CSV content
    const csvRows = [];
    
    // Add headers
    csvRows.push(headers.join(','));
    
    // Add data rows
    for (const row of data) {
      const values = headers.map(header => {
        const value = row[header];
        // Handle values with commas or quotes
        if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
          return `"${value.replace(/"/g, '""')}"`;
        }
        return value;
      });
      csvRows.push(values.join(','));
    }

    const csvContent = csvRows.join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', `${filename}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } catch (error) {
    console.error('Error exporting data as CSV:', error);
    throw new Error('Failed to export data as CSV');
  }
};

/**
 * Export data as JSON
 */
export const exportDataAsJSON = (
  data: any,
  filename: string = 'data'
): void => {
  try {
    const jsonContent = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonContent], { type: 'application/json;charset=utf-8;' });
    
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', `${filename}.json`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } catch (error) {
    console.error('Error exporting data as JSON:', error);
    throw new Error('Failed to export data as JSON');
  }
};

/**
 * Export chart data based on chart type and data
 */
export const exportChartData = (
  chartData: any,
  _chartType: string,
  filename: string = 'chart-data'
): void => {
  try {
    let exportData: Array<Record<string, any>> = [];

    // Transform chart data to exportable format
    if (chartData.data) {
      const { labels, datasets } = chartData.data;
      
      if (labels && datasets && datasets.length > 0) {
        exportData = labels.map((label: string, index: number) => {
          const row: Record<string, any> = { label };
          
          datasets.forEach((dataset: any, datasetIndex: number) => {
            const datasetLabel = dataset.label || `Dataset ${datasetIndex + 1}`;
            row[datasetLabel] = dataset.data[index];
          });
          
          return row;
        });
      }
    }

    if (exportData.length > 0) {
      exportDataAsCSV(exportData, filename);
    } else {
      throw new Error('No data available to export');
    }
  } catch (error) {
    console.error('Error exporting chart data:', error);
    throw new Error('Failed to export chart data');
  }
};
