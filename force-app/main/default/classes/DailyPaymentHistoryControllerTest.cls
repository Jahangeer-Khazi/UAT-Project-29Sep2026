/**
* @date Creation 12/10/2026
* @description : Test methods for DailyPaymentHistoryController
*                (Credit Card Payment Restriction - NBA-16942)
* @history Modifications :
*
*/
@isTest
public class DailyPaymentHistoryControllerTest {

    private static final String CIF = '123456';
    private static final String EMAIL = 'testclass@ilatest123.com';
    private static final String CANARY = 'aurora';

    /**
     * Returns a fixed response (or throws) and keeps the last request for assertions.
     */
    private class PaymentApiMock implements HttpCalloutMock {
        public Integer statusCode;
        public String body;
        public Boolean throwError = false;
        public HttpRequest lastRequest;

        public PaymentApiMock(Integer statusCode, String body) {
            this.statusCode = statusCode;
            this.body = body;
        }

        public HttpResponse respond(HttpRequest req) {
            lastRequest = req;
            if (throwError) {
                throw new CalloutException('Read timed out');
            }
            HttpResponse res = new HttpResponse();
            res.setHeader('Content-Type', 'application/json');
            res.setStatusCode(statusCode);
            res.setStatus(statusCode == 200 ? 'OK' : 'Error');
            if (body != null) {
                res.setBody(body);
            }
            return res;
        }
    }

    private static PaymentApiMock setMock(Integer statusCode, String body) {
        PaymentApiMock mock = new PaymentApiMock(statusCode, body);
        Test.setMock(HttpCalloutMock.class, mock);
        return mock;
    }

    private static PaymentApiMock setErrorMock() {
        PaymentApiMock mock = new PaymentApiMock(200, null);
        mock.throwError = true;
        Test.setMock(HttpCalloutMock.class, mock);
        return mock;
    }

    private static Id accountId() {
        return [SELECT Id FROM Account WHERE CIF__pc = :CIF LIMIT 1].Id;
    }

    @testSetup
    static void setupData() {
        TestDataFactory.createSObject(
            new Account(CIF__pc = CIF, Region_Flag__c = 'Bahrain', x_canary__pc = CANARY),
            'TestFactoryDefaults.AccountDefaults', true);
    }

    // ------------------------------------------------------------------
    // getDailyPaymentLimit
    // ------------------------------------------------------------------

    @isTest
    static void getDailyPaymentLimit_returnsLimits() {
        PaymentApiMock mock = setMock(200,
            '{"meta":{"code":"200","message":"Success"},' +
            '"data":{"maxDailyLimit":5000,"consumedDailyLimit":1200.50,"remainingDailyLimit":3799.50}}');

        Test.startTest();
        DailyPaymentHistoryController.PaymentLimitResponse res =
            DailyPaymentHistoryController.getDailyPaymentLimit(accountId());
        Test.stopTest();

        Assert.areEqual('Success', res.meta.message);
        Assert.areEqual(5000.0, res.data.maxDailyLimit);
        Assert.areEqual(1200.50, res.data.consumedDailyLimit);
        Assert.areEqual(3799.50, res.data.remainingDailyLimit);

        Assert.areEqual('GET', mock.lastRequest.getMethod());
        Assert.isTrue(mock.lastRequest.getEndpoint().contains('/api/v1/credit-cards/payment/limit'));
        Assert.areEqual(EMAIL, mock.lastRequest.getHeader('userId'));
        Assert.areEqual(CIF, mock.lastRequest.getHeader('customerId'));
        Assert.areEqual(CANARY, mock.lastRequest.getHeader('x-canary'));
    }

    @isTest
    static void getDailyPaymentLimit_throwsOnErrorStatus() {
        setMock(500, '{"meta":{"code":"500","message":"Internal error"}}');
        Boolean thrown = false;

        Test.startTest();
        try {
            DailyPaymentHistoryController.getDailyPaymentLimit(accountId());
        } catch (AuraHandledException e) {
            thrown = true;
        }
        Test.stopTest();

        Assert.isTrue(thrown, 'A non-200 response should raise an AuraHandledException');
    }

    // ------------------------------------------------------------------
    // getHistoryLogs
    // ------------------------------------------------------------------

    @isTest
    static void getHistoryLogs_returnsRecords() {
        PaymentApiMock mock = setMock(200,
            '{"meta":{"code":"200","message":"History found"},"data":[' +
            '{"previousTotalPaymentAmount":100,"maxDailyPaymentCap":5000,"paymentAmount":250.75,' +
            '"remainingDailyLimit":4649.25,"maskedCardNumber":"4111********1111","pciNumber":"PCI-1",' +
            '"status":"APPROVED","creationDatetime":"2026-10-01T10:15:00"},' +
            '{"paymentAmount":6000,"status":"RESTRICTED","maskedCardNumber":null}]}');

        Test.startTest();
        DailyPaymentHistoryController.HistoryLogsResponse res =
            DailyPaymentHistoryController.getHistoryLogs(accountId(), '2026-10-01');
        Test.stopTest();

        Assert.isTrue(res.success);
        Assert.areEqual('History found', res.message);
        Assert.areEqual(2, res.data.history.size());

        DailyPaymentHistoryController.HistoryRecord first = res.data.history[0];
        Assert.areEqual(100.0, first.previousTotalPaymentAmount);
        Assert.areEqual(5000.0, first.maxDailyPaymentCap);
        Assert.areEqual(250.75, first.paymentAmount);
        Assert.areEqual(4649.25, first.remainingDailyLimit);
        Assert.areEqual('4111********1111', first.maskedCardNumber);
        Assert.areEqual('PCI-1', first.pciNumber);
        Assert.areEqual('APPROVED', first.status);
        Assert.areEqual('2026-10-01T10:15:00', first.creationDatetime);

        // Missing and null values come back as null
        DailyPaymentHistoryController.HistoryRecord second = res.data.history[1];
        Assert.areEqual(6000.0, second.paymentAmount);
        Assert.isNull(second.maxDailyPaymentCap);
        Assert.isNull(second.maskedCardNumber);
        Assert.isNull(second.pciNumber);

        String endpoint = mock.lastRequest.getEndpoint();
        Assert.isTrue(endpoint.contains('/api/v1/credit-cards/payment/restriction/history'));
        Assert.isTrue(endpoint.contains('fromDate=2026-10-01'));
        Assert.isTrue(endpoint.contains('toDate=2026-10-01'));
        Assert.areEqual(CANARY, mock.lastRequest.getHeader('x-canary'));
    }

    @isTest
    static void getHistoryLogs_handlesMissingMetaAndData() {
        setMock(200, '{}');

        Test.startTest();
        DailyPaymentHistoryController.HistoryLogsResponse res =
            DailyPaymentHistoryController.getHistoryLogs(accountId(), '2026-10-01');
        Test.stopTest();

        Assert.isTrue(res.success);
        Assert.isNull(res.message);
        Assert.areEqual(0, res.data.history.size());
    }

    @isTest
    static void getHistoryLogs_requiresDate() {
        Test.startTest();
        DailyPaymentHistoryController.HistoryLogsResponse res =
            DailyPaymentHistoryController.getHistoryLogs(accountId(), '');
        Test.stopTest();

        Assert.isFalse(res.success);
        Assert.areEqual('Selected date is required.', res.message);
    }

    @isTest
    static void getHistoryLogs_rejectsInvalidDate() {
        Test.startTest();
        DailyPaymentHistoryController.HistoryLogsResponse res =
            DailyPaymentHistoryController.getHistoryLogs(accountId(), '01/10/2026');
        Test.stopTest();

        Assert.isFalse(res.success);
        Assert.areEqual('Invalid date format. Expected yyyy-MM-dd.', res.message);
    }

    @isTest
    static void getHistoryLogs_reportsErrorStatus() {
        setMock(404, '{"meta":{"code":"404","message":"Not found"}}');

        Test.startTest();
        DailyPaymentHistoryController.HistoryLogsResponse res =
            DailyPaymentHistoryController.getHistoryLogs(accountId(), '2026-10-01');
        Test.stopTest();

        Assert.isFalse(res.success);
        Assert.areEqual('History API returned HTTP status 404.', res.message);
    }

    @isTest
    static void getHistoryLogs_handlesCalloutException() {
        setErrorMock();

        Test.startTest();
        DailyPaymentHistoryController.HistoryLogsResponse res =
            DailyPaymentHistoryController.getHistoryLogs(accountId(), '2026-10-01');
        Test.stopTest();

        Assert.isFalse(res.success);
        Assert.isTrue(res.message.startsWith('Unable to retrieve payment history: '));
    }

    // ------------------------------------------------------------------
    // getWhitelistDetails
    // ------------------------------------------------------------------

    @isTest
    static void getWhitelistDetails_returnsWhitelists() {
        PaymentApiMock mock = setMock(200,
            '{"meta":{"code":"200","message":"Whitelist found"},"data":{"whitelists":[' +
            '{"id":7,"pciNumber":"PCI-1","whitelistedBy":"Agent One","fromDate":"2026-10-01",' +
            '"toDate":"2026-10-05","creationDatetime":"2026-10-01T09:00:00","expired":"false"}]}}');

        Test.startTest();
        DailyPaymentHistoryController.WhitelistResponse res =
            DailyPaymentHistoryController.getWhitelistDetails(accountId());
        Test.stopTest();

        Assert.isTrue(res.success);
        Assert.areEqual('Whitelist found', res.message);
        Assert.areEqual(1, res.data.whitelists.size());
        DailyPaymentHistoryController.WhitelistRecord rec = res.data.whitelists[0];
        Assert.areEqual(7, rec.id);
        Assert.areEqual('Agent One', rec.whitelistedBy);
        Assert.areEqual('2026-10-01', rec.fromDate);
        Assert.areEqual('2026-10-05', rec.toDate);
        Assert.areEqual('false', rec.expired);

        Assert.areEqual('GET', mock.lastRequest.getMethod());
        Assert.isTrue(mock.lastRequest.getEndpoint().contains('/api/v1/credit-cards/payment/whitelisted-customer'));
        Assert.areEqual(CIF, mock.lastRequest.getHeader('customerId'));
        Assert.areEqual(CANARY, mock.lastRequest.getHeader('x-canary'));
    }

    @isTest
    static void getWhitelistDetails_handlesMissingMeta() {
        setMock(200, '{"data":{"whitelists":[]}}');

        Test.startTest();
        DailyPaymentHistoryController.WhitelistResponse res =
            DailyPaymentHistoryController.getWhitelistDetails(accountId());
        Test.stopTest();

        Assert.isTrue(res.success);
        Assert.isNull(res.message);
        Assert.areEqual(0, res.data.whitelists.size());
    }

    @isTest
    static void getWhitelistDetails_reportsErrorStatus() {
        setMock(500, null);

        Test.startTest();
        DailyPaymentHistoryController.WhitelistResponse res =
            DailyPaymentHistoryController.getWhitelistDetails(accountId());
        Test.stopTest();

        Assert.isFalse(res.success);
        Assert.areEqual('Whitelist API failed. Status Code: 500', res.message);
    }

    @isTest
    static void getWhitelistDetails_handlesCalloutException() {
        setErrorMock();

        Test.startTest();
        DailyPaymentHistoryController.WhitelistResponse res =
            DailyPaymentHistoryController.getWhitelistDetails(accountId());
        Test.stopTest();

        Assert.isFalse(res.success);
        Assert.isTrue(res.message.startsWith('Unable to retrieve whitelist details: '));
    }

    // ------------------------------------------------------------------
    // createWhitelist
    // ------------------------------------------------------------------

    @isTest
    static void createWhitelist_postsRequest() {
        PaymentApiMock mock = setMock(200, '{"meta":{"code":"200","message":"Created"}}');

        Test.startTest();
        DailyPaymentHistoryController.WhitelistResponse res =
            DailyPaymentHistoryController.createWhitelist(accountId(), '2026-10-12', '2026-10-15');
        Test.stopTest();

        Assert.isTrue(res.success);
        Assert.areEqual('Customer whitelisted successfully.', res.message);

        Assert.areEqual('POST', mock.lastRequest.getMethod());
        Assert.isTrue(mock.lastRequest.getEndpoint().contains('/api/v1/credit-cards/payment/whitelisted-customer'));
        Assert.areEqual(CIF, mock.lastRequest.getHeader('customerId'));
        Map<String, Object> body = (Map<String, Object>) JSON.deserializeUntyped(mock.lastRequest.getBody());
        Assert.areEqual(UserInfo.getName(), body.get('whitelistedBy'));
        Assert.areEqual('2026-10-12', body.get('fromDate'));
        Assert.areEqual('2026-10-15', body.get('toDate'));
    }

    @isTest
    static void createWhitelist_reportsErrorStatus() {
        setMock(400, '{"meta":{"code":"400","message":"Invalid dates"}}');

        Test.startTest();
        DailyPaymentHistoryController.WhitelistResponse res =
            DailyPaymentHistoryController.createWhitelist(accountId(), '2026-10-15', '2026-10-12');
        Test.stopTest();

        Assert.isFalse(res.success);
        Assert.areEqual('Whitelist API failed. Status Code: 400', res.message);
    }

    @isTest
    static void createWhitelist_handlesCalloutException() {
        setErrorMock();

        Test.startTest();
        DailyPaymentHistoryController.WhitelistResponse res =
            DailyPaymentHistoryController.createWhitelist(accountId(), '2026-10-12', '2026-10-15');
        Test.stopTest();

        Assert.isFalse(res.success);
        Assert.isTrue(res.message.startsWith('Unable to whitelist customer: '));
    }
}
