import type {
  IExecuteFunctions,
  INodeExecutionData,
  INodeType,
  INodeTypeDescription,
} from "n8n-workflow";
import { Saaf } from "@safearly/saaf";

/**
 * n8n node: scan or mask Indian PII in a field before it reaches an AI node.
 * Mask writes the masked text to `outputField`; the token map stays in the
 * node's memory for this execution only and is never written to item data.
 */
export class SaafNode implements INodeType {
  description: INodeTypeDescription = {
    displayName: "Saaf PII",
    name: "saaf",
    icon: "file:saaf.svg",
    group: ["transform"],
    version: 1,
    subtitle: '={{$parameter["operation"]}}',
    description: "Detect or mask Aadhaar, PAN, GSTIN, UPI and other Indian PII",
    defaults: { name: "Saaf PII" },
    inputs: ["main"],
    outputs: ["main"],
    properties: [
      {
        displayName: "Operation",
        name: "operation",
        type: "options",
        noDataExpression: true,
        options: [
          { name: "Scan", value: "scan", description: "Add entity types and counts, change nothing" },
          { name: "Mask", value: "mask", description: "Replace PII with tokens like [PAN_1]" },
        ],
        default: "mask",
      },
      { displayName: "Input Field", name: "inputField", type: "string", default: "text" },
      { displayName: "Output Field", name: "outputField", type: "string", default: "text_masked",
        displayOptions: { show: { operation: ["mask"] } } },
      { displayName: "Fail on Detection", name: "failOnDetection", type: "boolean", default: false },
    ],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const out: INodeExecutionData[] = [];
    for (let i = 0; i < items.length; i++) {
      const op = this.getNodeParameter("operation", i) as string;
      const field = this.getNodeParameter("inputField", i) as string;
      const fail = this.getNodeParameter("failOnDetection", i) as boolean;
      const text = String(items[i]!.json[field] ?? "");
      const saaf = new Saaf();
      const r = saaf.mask(text);
      if (fail && r.applied.length) {
        throw new Error(`Saaf: personal data found in item ${i}: ${JSON.stringify(r.entityCounts)}`);
      }
      const json = { ...items[i]!.json, saaf_entities: r.entityCounts };
      if (op === "mask") {
        (json as Record<string, unknown>)[this.getNodeParameter("outputField", i) as string] = r.text;
      }
      out.push({ json });
    }
    return [out];
  }
}
