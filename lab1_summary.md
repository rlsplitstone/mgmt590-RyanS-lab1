# lab1_summary
## By: Ryan Splitstone | MGMT590 | Summer 2025
## GCP Project Info: Project ID: mgmt599-ryansplitstone-lab1 | Project Number: 357515825942
## Time Spent: Task 1: 60 minutes | Task 2: 45 minutes | Task 3: 3 hours

### Discover – Cross-Functional Patterns & Key Metrics

Superstore's data reveals **strong seasonality** and **regional imbalances**. Q4 holiday sales surge about 30% above Q1 lulls, and each subsequent Q4 has topped the prior year. Regionally, the **West** commands roughly 33% of sales (~$725K) and enjoys 22% profit margins, while the **East** follows with 29% and strong profitability. In contrast, **Central** and **South** together contribute 39% of sales ($501K and $392K respectively) but post near zero or negative profits due to deep discounting, with Central averaging the highest discount rate at 17%.

Product performance is equally polarized: the **Technology** category drives the highest revenue ($836K) and margins, whereas **Furniture** produces substantial revenue ($742K) yet suffers thin or negative margins because average discounts exceed 17%. Customer behavior follows a **Pareto distribution**, 20% of customers account for 80% of revenue, yet high spend does not guarantee profit: some top spenders generate net losses due to discounted purchases. Moreover, roughly 70% of customers are one-and-done, leaving retention potential largely untapped.

### Investigate – Root Causes and Connections

**Time series decomposition** confirms that Q4 spikes are structural, driven by holiday demand, while a July anomaly stemmed from targeted promotions. Shipping analysis shows uniform delivery times (~3.9 days) across regions, ruling out logistics and implicating pricing: the Central region's 17% average discount effectively "buys" revenue at the expense of margins. 

**Furniture's margin problems** stem from high discounts (17-23%) and hidden fulfillment costs, and correlation analysis shows a significant negative relationship between discount rate and profitability (p < 0.01). The strongest negative correlation between discounts and profitability appears in Furniture products (-0.68). Segmentation reveals that corporate customers make larger, more frequent purchases with lower price sensitivity, whereas consumer segments display higher discount responsiveness and contribute to the 70% one-and-done rate. The Central region has the highest proportion of Consumer segment customers (51%), contributing to higher overall discount rates.

### Validate – Reconciling Conflicts & Data Limitations

Cross-domain validation reconciles seemingly conflicting signals. Central's high revenue is discount-driven and unprofitable, and some high-revenue customers produce losses. Aligning customer behavior findings with product and regional data confirms that technology-focused customers are more profitable, while furniture-heavy baskets often erode margins. 

**Data limitations** include missing cost data on product costs, shipping expenses, and local operating costs, which could be critical confounders. The Central region has a significantly higher percentage of profit margin outliers (22.4% vs. 12-15% in other regions), which could disproportionately influence our conclusions. Additionally, we lack information about regional competition intensity, which might explain the necessity for Central's high discounts.

Despite these limitations, the strong negative correlation between discount and profitability holds across all time periods and segments, and the product mix differences between regions are statistically significant and consistent over time, strengthening confidence in these insights.

### Extend – Strategic Priorities and Actions

1. **Seasonal & Regional Optimization.** Build ML-based demand forecasts by Q3 to anticipate the 30% Q4 surge, scale inventory and staffing accordingly, and avoid stockouts. Replicate the West's playbook in underperforming regions by adjusting product mix and marketing to local preferences. Implement category-specific discount caps by region, with stricter limits in the Central region and for Furniture products (15% maximum discount cap on Furniture in Central, down from current 23%). **Success metrics**: stockout rates <2%, 15%+ revenue growth in Central/South, 5 percentage point margin improvement, and 3-5 percentage point improvement in Furniture profit margin.

2. **Customer Lifetime Value Enhancement.** Shift focus from acquisition to retention; acquiring new customers costs 5–25× more, and a 5% retention lift can boost profits 25–95%. Launch a tiered loyalty program, automate post-purchase engagement (day 20–25), offer VIP benefits to the top 20% customers, and deploy churn models to trigger win-back offers. Implement segment-specific pricing strategies based on price sensitivity analysis, with more conservative discounting for the Consumer segment, especially in the Central region. **Target outcomes**: raise repeat purchase rates from 30% to 40% and improve CLV by 20%.

3. **Margin-Focused Product & Pricing Strategy.** Institute pricing guardrails that cap discounts on low-margin categories and adjust discount levels dynamically based on demand signals. Bundle furniture with higher-margin accessories, negotiate better supplier terms, and restructure sales incentives to reward profitable revenue rather than volume. Address subcategory issues by implementing a 20% cap on Tables and Bookcases across all regions and developing a tiered approval system for exceeding discount thresholds. **Expected results**: raising furniture margins above 5%, lowering average discount rate from 15.6% to 12%, and ensuring profit growth outpaces revenue growth.

### Conclusion

Superstore's challenges are interlinked across sales, customer behavior, product economics, and regional operations. The data clearly shows that excessive discounting, particularly in the Central region and with Furniture products, is significantly eroding profitability. By implementing region and category-specific discount strategies, focusing on customer retention, and adjusting the product mix to favor higher-margin items, Superstore can transform high-volume but low-margin segments into engines of sustainable growth and profitability.

*Analysis conducted using Python data analysis tools including pandas, matplotlib, seaborn, and statistical testing methods on the Superstore dataset (2019-2022).*
