public with sharing class LoginActivityService {

    private static final String LOGIN_HISTORY_PATH = '/api/v1/login-history';
    private static final Integer DEFAULT_LOOKBACK_DAYS = 30;
    private static final Integer DEFAULT_LIMIT = 1;
    private static final Integer MAX_PAGES = 10;

    @TestVisible
    private static ApiConnection connection = new ApiConnection();

    public class FetchResult {
        public List<Map<String, Object>> items = new List<Map<String, Object>>();
        public String region;
        public String cif;
    }

    /**
     * Scan one-day API windows, newest first.
     * Limited to 8 days per call so we stay under the gateway's burst limit
     * (the 10th rapid callout returns GENE-3001).
     * startDaysAgo / daysToScan are optional; omitted values scan the last 8 days.
     */
    @AuraEnabled
    public static LoginActivityWrapper getLastLoginAttempt(Id customerId, Integer startDaysAgo, Integer daysToScan) {
        Account customer = getCustomer(customerId);
        Integer start = startDaysAgo == null || startDaysAgo < 0 ? 0 : startDaysAgo;
        Integer scan = daysToScan == null || daysToScan < 1 ? 8 : daysToScan;
        if (scan > 8) {
            scan = 8;
        }

        String region = resolveRegion(customer);
        Date startDay = Date.today().addDays(-start);
        for (Integer i = 0; i < scan; i++) {
            Date day = startDay.addDays(-i);
            ApiPage page = callLoginHistory(customer, day, day, DEFAULT_LIMIT, null);
            if (!page.isSuccess) {
                if (isRetryableApiError(page)) {
                    break;
                }
                throwAura('Login history API call failed: ' + page.errorMessage);
            }
            if (!page.items.isEmpty()) {
                return pickLatest(page.items, region);
            }
        }
        return null;
    }

    public static FetchResult scanLoginDays(Id customerId, Integer startDaysAgo, Integer daysToScan) {
        Account customer = getCustomer(customerId);
        Integer start = startDaysAgo == null || startDaysAgo < 0 ? 0 : startDaysAgo;
        Integer scan = daysToScan == null || daysToScan < 1 ? 8 : daysToScan;
        if (scan > 8) {
            scan = 8;
        }

        FetchResult result = new FetchResult();
        result.cif = customer.CIF__pc.trim();
        result.region = resolveRegion(customer);

        Date startDay = Date.today().addDays(-start);
        for (Integer i = 0; i < scan; i++) {
            Date day = startDay.addDays(-i);
            ApiPage page = callLoginHistory(customer, day, day, DEFAULT_LIMIT, null);
            if (!page.isSuccess) {
                if (isRetryableApiError(page)) {
                    break;
                }
                throwAura('Login history API call failed: ' + page.errorMessage);
            }
            result.items.addAll(page.items);
        }
        return result;
    }

    @AuraEnabled
    public static List<LoginActivityWrapper> getLoginHistory(Id customerId, Date fromDate, Date toDate, String status) {
        FetchResult fetched = fetchLoginHistoryItems(
            customerId,
            fromDate,
            toDate,
            DEFAULT_LIMIT,
            true
        );

        List<LoginActivityWrapper> mapped = new List<LoginActivityWrapper>();
        for (Map<String, Object> item : fetched.items) {
            LoginActivityWrapper row = mapToWrapper(item, fetched.region);
            if (matchesStatus(row.status, status)) {
                mapped.add(row);
            }
        }
        return mapped;
    }

    @AuraEnabled
    public static String generateExportUrl(Id customerId, Date fromDate, Date toDate, String status) {
        return 'https://mock-api.arabbank.com/reports/login-activity?customerId=' + customerId + '&from=' + fromDate + '&to=' + toDate + '&format=excel';
    }

    public static FetchResult fetchLoginHistoryItems(
        Id customerId,
        Date fromDate,
        Date toDate,
        Integer limitVal,
        Boolean followAllPages
    ) {
        Account customer = getCustomer(customerId);
        Date effectiveTo = toDate != null ? toDate : Date.today();
        Date effectiveFrom = fromDate != null ? fromDate : effectiveTo.addDays(-DEFAULT_LOOKBACK_DAYS);
        if (effectiveFrom > effectiveTo) {
            Date swapped = effectiveFrom;
            effectiveFrom = effectiveTo;
            effectiveTo = swapped;
        }

        FetchResult result = new FetchResult();
        result.cif = customer.CIF__pc.trim();
        result.region = resolveRegion(customer);

        Integer originalSpan = effectiveFrom.daysBetween(effectiveTo);
        List<Integer> windows = new List<Integer>{ originalSpan };
        if (originalSpan > 7) {
            windows.add(7);
        }
        if (originalSpan > 1) {
            windows.add(1);
        }

        ApiPage lastPage;
        for (Integer windowDays : windows) {
            if (windowDays == null || windowDays < 0) {
                continue;
            }
            Date windowFrom = effectiveTo.addDays(-windowDays);
            if (windowFrom < effectiveFrom) {
                windowFrom = effectiveFrom;
            }
            lastPage = fetchRange(customer, windowFrom, effectiveTo, DEFAULT_LIMIT, followAllPages);
            if (lastPage.isSuccess) {
                result.items.addAll(lastPage.items);
                return result;
            }
            if (!isRetryableApiError(lastPage)) {
                throwAura('Login history API call failed: ' + lastPage.errorMessage);
            }
        }

        if (lastPage != null && !lastPage.isSuccess && followAllPages == true) {
            throwAura('Login history API call failed: ' + lastPage.errorMessage);
        }
        return result;
    }

    private class ApiPage {
        public List<Map<String, Object>> items = new List<Map<String, Object>>();
        public String nextToken;
        public Integer statusCode;
        public String errorMessage;
        public Boolean isSuccess;
    }

    private static ApiPage fetchRange(
        Account customer,
        Date fromDate,
        Date toDate,
        Integer limitVal,
        Boolean followAllPages
    ) {
        ApiPage combined = new ApiPage();
        combined.items = new List<Map<String, Object>>();
        combined.isSuccess = true;
        combined.statusCode = 200;

        String nextToken = null;
        Integer page = 0;
        Integer pagesToFetch = followAllPages == true ? MAX_PAGES : 1;

        do {
            page++;
            ApiPage apiPage = callLoginHistory(customer, fromDate, toDate, limitVal, nextToken);
            if (!apiPage.isSuccess) {
                return apiPage;
            }
            combined.items.addAll(apiPage.items);
            nextToken = apiPage.nextToken;
        } while (followAllPages == true && String.isNotBlank(nextToken) && page < pagesToFetch);

        return combined;
    }

    private static ApiPage callLoginHistory(
        Account customer,
        Date fromDate,
        Date toDate,
        Integer limitVal,
        String nextToken
    ) {
        String cif = customer.CIF__pc.trim();
        String region = resolveRegion(customer);

        List<String> parts = new List<String>{
            'cif=' + EncodingUtil.urlEncode(cif, 'UTF-8'),
            'startDate=' + EncodingUtil.urlEncode(toStartOfDayUtc(fromDate), 'UTF-8'),
            'endDate=' + EncodingUtil.urlEncode(toExclusiveEndUtc(toDate), 'UTF-8')
        };
        if (limitVal != null) {
            parts.add('limit=' + String.valueOf(limitVal));
        }
        if (String.isNotBlank(nextToken)) {
            parts.add('nextToken=' + EncodingUtil.urlEncode(nextToken, 'UTF-8'));
        }

        String path = LOGIN_HISTORY_PATH + '?' + String.join(parts, '&');
        HttpRequest req = connection.createRequest('GET', path, region);
        req.setHeader('Accept', 'application/json');
        req.setTimeout(120000);

        System.debug('Login history endpoint: ' + req.getEndpoint());
        HTTPResponse httpRes = new Http().send(req);
        System.debug('Login history status: ' + (httpRes == null ? null : httpRes.getStatusCode()));
        System.debug('Login history body: ' + (httpRes == null ? null : httpRes.getBody()));

        ApiPage page = new ApiPage();
        page.statusCode = httpRes == null ? 0 : httpRes.getStatusCode();
        page.isSuccess = page.statusCode == 200;
        if (!page.isSuccess) {
            page.errorMessage = extractHttpError(httpRes);
            page.items = new List<Map<String, Object>>();
            return page;
        }

        Object payload = null;
        if (httpRes != null && String.isNotBlank(httpRes.getBody())) {
            payload = JSON.deserializeUntyped(httpRes.getBody());
        }
        ApiPage parsed = parseApiPage(payload);
        parsed.statusCode = 200;
        parsed.isSuccess = true;
        return parsed;
    }

    private static Boolean isRetryableApiError(ApiPage page) {
        if (page == null || page.isSuccess) {
            return false;
        }
        String message = page.errorMessage == null ? '' : page.errorMessage;
        return page.statusCode == 500
            || message.contains('GENE-3001')
            || message.containsIgnoreCase('unable to provide access');
    }

    @TestVisible
    static ApiPage parseApiPage(Object responseData) {
        ApiPage page = new ApiPage();
        Map<String, Object> payload = extractPayload(responseData);
        if (payload == null) {
            return page;
        }

        Object rawItems = payload.get('items');
        if (rawItems instanceof List<Object>) {
            for (Object rawItem : (List<Object>) rawItems) {
                if (rawItem instanceof Map<String, Object>) {
                    page.items.add((Map<String, Object>) rawItem);
                }
            }
        }

        Object tokenObj = payload.get('nextToken');
        if (tokenObj != null) {
            String token = String.valueOf(tokenObj);
            if (String.isNotBlank(token) && token != 'null') {
                page.nextToken = token;
            }
        }
        return page;
    }

    private static Map<String, Object> extractPayload(Object responseData) {
        if (!(responseData instanceof Map<String, Object>)) {
            return null;
        }
        Map<String, Object> payload = (Map<String, Object>) responseData;
        if (payload.containsKey('items')) {
            return payload;
        }
        Object nested = payload.get('data');
        if (nested instanceof Map<String, Object>) {
            return (Map<String, Object>) nested;
        }
        return payload;
    }

    private static LoginActivityWrapper pickLatest(List<Map<String, Object>> items, String region) {
        LoginActivityWrapper latest = null;
        for (Map<String, Object> item : items) {
            LoginActivityWrapper row = mapToWrapper(item, region);
            if (latest == null
                || (row.loginTimestamp != null
                    && (latest.loginTimestamp == null || row.loginTimestamp > latest.loginTimestamp))) {
                latest = row;
            }
        }
        return latest;
    }

    private static LoginActivityWrapper mapToWrapper(Map<String, Object> item, String region) {
        LoginActivityWrapper row = new LoginActivityWrapper();
        row.loginTimestamp = parseTimestamp(item.get('timestamp'));
        row.status = mapOutcome(toStringValue(item.get('outcome')));
        row.deviceIp = toStringValue(item.get('ipAddress'));
        row.deviceModel = toStringValue(item.get('deviceId'));
        row.location = toStringValue(item.get('city'));
        row.unit = region;
        row.errorCode = row.status == 'Failed' ? toStringValue(item.get('errorCode')) : '';
        row.vpnUsed = false;
        return row;
    }

    private static Boolean matchesStatus(String actualStatus, String requestedStatus) {
        return String.isBlank(requestedStatus)
            || requestedStatus == 'All'
            || actualStatus == requestedStatus;
    }

    private static Account getCustomer(Id customerId) {
        if (customerId == null) {
            throwAura('Customer Id is required to load login history.');
        }
        List<Account> accounts = [
            SELECT CIF__pc, Region_Flag__c, Region_Flag__pc
            FROM Account
            WHERE Id = :customerId
            LIMIT 1
        ];
        if (accounts.isEmpty()) {
            throwAura('Customer account was not found.');
        }
        if (String.isBlank(accounts[0].CIF__pc)) {
            throwAura('CIF is missing on the customer account.');
        }
        return accounts[0];
    }

    private static String resolveRegion(Account customer) {
        if (String.isNotBlank(customer.Region_Flag__c)) {
            return customer.Region_Flag__c;
        }
        if (String.isNotBlank(customer.Region_Flag__pc)) {
            return customer.Region_Flag__pc;
        }
        return 'Bahrain';
    }

    private static String toStartOfDayUtc(Date value) {
        Datetime dt = Datetime.newInstanceGmt(value.year(), value.month(), value.day(), 0, 0, 0);
        return dt.formatGmt('yyyy-MM-dd\'T\'HH:mm:ss\'Z\'');
    }

    private static String toExclusiveEndUtc(Date value) {
        Date nextDay = value.addDays(1);
        Datetime dt = Datetime.newInstanceGmt(nextDay.year(), nextDay.month(), nextDay.day(), 0, 0, 0);
        return dt.formatGmt('yyyy-MM-dd\'T\'HH:mm:ss\'Z\'');
    }

    public static String mapOutcome(String outcome) {
        if (String.isBlank(outcome)) {
            return '';
        }
        if (outcome.equalsIgnoreCase('SUCCESS')) {
            return 'Success';
        }
        if (outcome.equalsIgnoreCase('FAILED')
            || outcome.equalsIgnoreCase('FAILURE')
            || outcome.equalsIgnoreCase('FAIL')) {
            return 'Failed';
        }
        return outcome.substring(0, 1).toUpperCase() + outcome.substring(1).toLowerCase();
    }

    public static Datetime parseTimestamp(Object raw) {
        if (raw == null) {
            return null;
        }
        String value = String.valueOf(raw);
        if (String.isBlank(value)) {
            return null;
        }
        try {
            return (Datetime) JSON.deserialize('"' + value + '"', Datetime.class);
        } catch (Exception e) {
            return null;
        }
    }

    public static String toStringValue(Object raw) {
        return raw == null ? '' : String.valueOf(raw);
    }

    private static String extractHttpError(HTTPResponse httpRes) {
        if (httpRes == null) {
            return 'Unknown error';
        }
        String body = httpRes.getBody();
        if (String.isNotBlank(body)) {
            try {
                Object parsed = JSON.deserializeUntyped(body);
                if (parsed instanceof Map<String, Object>) {
                    Map<String, Object> errorMap = (Map<String, Object>) parsed;
                    Object meta = errorMap.containsKey('meta') ? errorMap.get('meta') : errorMap;
                    if (meta instanceof Map<String, Object>) {
                        Map<String, Object> metaMap = (Map<String, Object>) meta;
                        if (metaMap.get('message') != null) {
                            return String.valueOf(metaMap.get('message'));
                        }
                    }
                    return String.valueOf(meta);
                }
            } catch (Exception e) {
                return body;
            }
            return body;
        }
        return 'HTTP ' + String.valueOf(httpRes.getStatusCode());
    }

    private static void throwAura(String message) {
        AuraHandledException ex = new AuraHandledException(message);
        ex.setMessage(message);
        throw ex;
    }
}