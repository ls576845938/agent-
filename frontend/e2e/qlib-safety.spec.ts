import {test,expect} from '@playwright/test';

test('crypto initial navigation never polls private observation',async({page})=>{
 const privateRequests:string[]=[];
 page.on('request',request=>{if(/private|\/orders?(\/|$)/.test(new URL(request.url()).pathname))privateRequests.push(request.url());});
 await page.route('**/api/**',route=>route.fulfill({status:503,json:{detail:'fixture_missing_public_evidence'}}));
 await page.goto('/crypto');
 await expect(page.locator('body')).toBeVisible();
 await page.waitForTimeout(1000);
 expect(privateRequests).toEqual([]);
});
