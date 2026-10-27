/*      Organization : ABC Bank
*      Created By: Jahangeer Mohammed
*      Created Date: 27-10-2026
*      Description : Test class for JoCreditCardApplicationController
*      Change History:
*           #CH01# #Jahangeer Mohammed# #27-10-2026# Added test coverage for getCardConfigurations and getloadCreditCardBankList
*                  (Jordan Balance Transfer Process - NBA-15608). New test methods:
*                    - getCardConfigurations_Success_Test     : 200 response, only card options with productMappingCode are returned,
*                                                               keyed by productMappingCode (x-canary header branch covered)
*                    - getCardConfigurations_Alburaq_Test     : caseModel 'alburaq' builds the '<Region>_alburaq' region name
*                    - getCardConfigurations_Failure_Test     : non-200 response returns an empty map
*                    - getloadCreditCardBankList_Success_Test : 200 response is mapped into key/value bank options
*                    - getloadCreditCardBankList_Failure_Test : non-200 response returns an empty list
*                    - getloadCreditCardBankList_Exception_Test : invalid response body is caught and returns an empty list
*/
@isTest
public class JoCreditCardApplicationControllerTest {

    private static final String JORDAN_REGION = 'Jordan';
    private static final String CARD_CONFIG_RESPONSE = '{"meta":{"code":"CCRD-1000","message":"Success"},"data":{"cardOptions":['+
        '{"productMappingCode":"PLATINUM_CASHBACK_AND_REWARD_01","cardConfigurations":['+
        '{"configCode":"BT_MINIMUM_ISSUER_LIMIT","configValue":"1000"},'+
        '{"configCode":"BT_LIMIT_PROMOTION_PERCENTAGE","configValue":"0.25"},'+
        '{"configCode":"CC_BALANCE_TRANSFER_TENURES_CONFIG","configValue":"[{\\"tenurePeriod\\":6,\\"balanceTransferTenureCode\\":1,\\"oneTimeFeePercentage\\":2,\\"balanceTransferOfferCode\\":\\"BT6\\"}]"}]},'+
        '{"cardName":"NO_MAPPING_CODE"}]}}';
    private static final String BANK_LIST_RESPONSE = '{"meta":{"code":"CNT-1000","message":"Success"},"data":{"resources":['+
        '{"key":"Arab Bank","value":"ARAB_BANK"},{"key":"Housing Bank","value":"HOUSING_BANK"}]}}';

    private class CalloutMock implements HttpCalloutMock{
        private Integer statusCode;
        private String body;
        CalloutMock(Integer statusCode, String body){
            this.statusCode = statusCode;
            this.body = body;
        }
        public HttpResponse respond(HttpRequest req){
            HttpResponse res = new HttpResponse();
            res.setHeader('Content-Type', 'application/json');
            res.setStatusCode(statusCode);
            res.setBody(body);
            return res;
        }
    }

    @testSetup
    static void setupData(){
        Account acc = new Account();
        acc.FirstName = 'Jordan';
        acc.LastName = 'BalanceTransfer';
        acc.PersonEmail = 'jordan.bt@ilatest.com';
        acc.CIF__pc = '7654321';
        acc.Region_Flag__c = JORDAN_REGION;
        acc.Region_Flag__pc = JORDAN_REGION;
        acc.x_canary__pc = 'canary';
        insert acc;
    }

    private static Account getAccount(){
        return [SELECT Id FROM Account WHERE PersonEmail = 'jordan.bt@ilatest.com' LIMIT 1];
    }

    //CH01: Start
    @isTest
    static void getCardConfigurations_Success_Test(){
        Account acc = getAccount();
        Test.setMock(HttpCalloutMock.class, new CalloutMock(200, CARD_CONFIG_RESPONSE));
        Test.startTest();
            Map<String,Object> result = JoCreditCardApplicationController.getCardConfigurations(acc.Id, 'ila');
        Test.stopTest();
        System.assertEquals(1, result.size(), 'Only card options with productMappingCode should be returned');
        System.assert(result.containsKey('PLATINUM_CASHBACK_AND_REWARD_01'), 'Card option should be keyed by productMappingCode');
        Map<String,Object> cardOption = (Map<String,Object>)result.get('PLATINUM_CASHBACK_AND_REWARD_01');
        System.assertEquals(3, ((List<Object>)cardOption.get('cardConfigurations')).size(), 'Card configurations should be returned as received');
    }

    @isTest
    static void getCardConfigurations_Alburaq_Test(){
        Account acc = getAccount();
        Test.setMock(HttpCalloutMock.class, new CalloutMock(200, CARD_CONFIG_RESPONSE));
        Test.startTest();
            Map<String,Object> result = JoCreditCardApplicationController.getCardConfigurations(acc.Id, 'alburaq');
        Test.stopTest();
        System.assert(result.containsKey('PLATINUM_CASHBACK_AND_REWARD_01'), 'Alburaq card configurations should be returned');
    }

    @isTest
    static void getCardConfigurations_Failure_Test(){
        Account acc = getAccount();
        Test.setMock(HttpCalloutMock.class, new CalloutMock(500, '{"meta":{"code":"ERR-500","message":"Internal Server Error"}}'));
        Test.startTest();
            Map<String,Object> result = JoCreditCardApplicationController.getCardConfigurations(acc.Id, 'ila');
        Test.stopTest();
        System.assertEquals(0, result.size(), 'Failed API call should return an empty map');
    }

    @isTest
    static void getloadCreditCardBankList_Success_Test(){
        Account acc = getAccount();
        Test.setMock(HttpCalloutMock.class, new CalloutMock(200, BANK_LIST_RESPONSE));
        Test.startTest();
            List<Map<String,String>> result = JoCreditCardApplicationController.getloadCreditCardBankList(acc.Id);
        Test.stopTest();
        System.assertEquals(2, result.size(), 'All banks from the response should be returned');
        System.assertEquals('Arab Bank', result[0].get('key'), 'Bank key should be mapped');
        System.assertEquals('ARAB_BANK', result[0].get('value'), 'Bank value should be mapped');
    }

    @isTest
    static void getloadCreditCardBankList_Failure_Test(){
        Account acc = getAccount();
        Test.setMock(HttpCalloutMock.class, new CalloutMock(404, '{"meta":{"code":"ERR-404","message":"Not Found"}}'));
        Test.startTest();
            List<Map<String,String>> result = JoCreditCardApplicationController.getloadCreditCardBankList(acc.Id);
        Test.stopTest();
        System.assertEquals(0, result.size(), 'Failed API call should return an empty list');
    }

    @isTest
    static void getloadCreditCardBankList_Exception_Test(){
        Account acc = getAccount();
        Test.setMock(HttpCalloutMock.class, new CalloutMock(200, 'Invalid JSON'));
        Test.startTest();
            List<Map<String,String>> result = JoCreditCardApplicationController.getloadCreditCardBankList(acc.Id);
        Test.stopTest();
        System.assertEquals(0, result.size(), 'Invalid response should be handled and return an empty list');
    }
    //CH01: END
}
