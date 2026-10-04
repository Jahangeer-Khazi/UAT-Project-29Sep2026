import { LightningElement, api, track } from 'lwc';
import getRecentActivityDetails from '@salesforce/apex/LoginActivityDetailsService.getRecentActivityDetails';
import getCustomerExportInfo from '@salesforce/apex/LoginActivityDetailsService.getCustomerExportInfo';
import { ShowToastEvent } from 'lightning/platformShowToastEvent';

const COLUMNS = [
    { label: 'Timestamp', fieldName: 'timestamp', type: 'date', typeAttributes: { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' } },
    { label: 'Result', fieldName: 'result', type: 'text' },
    { label: 'Device ID', fieldName: 'channel', type: 'text' },
    { label: 'IP Address', fieldName: 'category', type: 'text' },
    { label: 'Location', fieldName: 'unit', type: 'text' },
    { label: 'Description', fieldName: 'description', type: 'text' },
    { label: 'Error', fieldName: 'errorCode', type: 'text' }
];

export default class Lwc07_LoginActivityDetailsTracker extends LightningElement {
    @api recordId;
    @api pageSize = 50;
    @api maxRangeMonths = 3;

    @track recentActivity = [];
    @track historyData = [];
    @track fullHistory = [];
    @track error;
    @track isLoading = true;
    @track isExpanded = false;

    // Report Generation
    @track isReportPanelOpen = false;
    reportFromDate;
    reportToDate;
    reportResult = 'All';
    customerName;
    customerCif;

    // Expanded View Filters
    filterFromDate;
    filterToDate;
    filterStatus = '';

    // Pagination
    currentPage = 1;
    totalPages = 1;

    columns = COLUMNS;

    get statusOptions() {
        return [
            { label: 'All', value: '' },
            { label: 'Success', value: 'Success' },
            { label: 'Failed', value: 'Failed' }
        ];
    }

    get reportResultOptions() {
        return [
            { label: 'All', value: 'All' },
            { label: 'Success', value: 'Success' },
            { label: 'Failed', value: 'Failed' }
        ];
    }

    get hasData() {
        return this.recentActivity && this.recentActivity.length > 0;
    }

    get isFirstPage() { return this.currentPage === 1; }
    get isLastPage() { return this.currentPage >= this.totalPages; }

    get pageList() {
        const total = this.totalPages;
        const current = this.currentPage;
        const delta = 2;
        const range = [];
        const rangeWithDots = [];

        for (let i = 1; i <= total; i++) {
            if (i === 1 || i === total || (i >= current - delta && i <= current + delta)) {
                range.push(i);
            }
        }

        let l;
        for (let i of range) {
            if (l) {
                if (i - l === 2) {
                    rangeWithDots.push({ label: l + 1, value: l + 1, isDots: false, variant: 'neutral' });
                } else if (i - l !== 1) {
                    rangeWithDots.push({ label: '...', value: 'dots', isDots: true, variant: 'base' });
                }
            }
            rangeWithDots.push({
                label: i,
                value: i,
                isDots: false,
                variant: i === current ? 'brand' : 'neutral'
            });
            l = i;
        }
        return rangeWithDots;
    }

    connectedCallback() {
        this.loadRecent();
        const end = new Date();
        const start = new Date();
        start.setDate(end.getDate() - 30);
        this.filterToDate = end.toISOString().split('T')[0];
        this.filterFromDate = start.toISOString().split('T')[0];
        this.reportToDate = end.toISOString().split('T')[0];
        this.reportFromDate = start.toISOString().split('T')[0];
    }

    daysAgoFromToday(dateStr) {
        const target = new Date(dateStr);
        const today = new Date();
        target.setHours(0, 0, 0, 0);
        today.setHours(0, 0, 0, 0);
        return Math.round((today.getTime() - target.getTime()) / (1000 * 60 * 60 * 24));
    }

    mapDetailRows(items) {
        return (items || []).map((item, index) => ({
            ...item,
            id: item.id || (item.timestamp + '-' + index),
            badgeClass: item.result === 'Success' ? 'slds-theme_success' : 'slds-theme_error'
        }));
    }

    async fetchChunks(startDaysAgo, totalDays) {
        const rows = [];
        const chunkSize = 8;
        for (let offset = 0; offset < totalDays; offset += chunkSize) {
            const chunk = await getRecentActivityDetails({
                customerId: this.recordId,
                startDaysAgo: startDaysAgo + offset,
                daysToScan: Math.min(chunkSize, totalDays - offset)
            });
            rows.push(...(chunk || []));
        }
        return rows;
    }

    async loadRecent() {
        this.isLoading = true;
        try {
            const items = await this.fetchChunks(0, 32);
            this.recentActivity = this.mapDetailRows(items).slice(0, 5);
            this.error = undefined;
        } catch (error) {
            this.error = this.reduceErrors(error);
            this.recentActivity = [];
        } finally {
            this.isLoading = false;
        }
    }

    async loadHistory() {
        this.isLoading = true;
        try {
            const startAgo = Math.max(0, this.daysAgoFromToday(this.filterToDate));
            const fromAgo = Math.max(startAgo, this.daysAgoFromToday(this.filterFromDate));
            const totalDays = Math.max(1, fromAgo - startAgo + 1);
            let items = await this.fetchChunks(startAgo, totalDays);
            if (this.filterStatus) {
                items = items.filter(item => item.result === this.filterStatus);
            }
            this.fullHistory = this.mapDetailRows(items);
            this.totalPages = Math.max(1, Math.ceil(this.fullHistory.length / this.pageSize));
            this.currentPage = 1;
            this.applyHistoryPage();
            this.error = undefined;
        } catch (error) {
            this.error = this.reduceErrors(error);
            this.historyData = [];
            this.fullHistory = [];
        } finally {
            this.isLoading = false;
        }
    }

    applyHistoryPage() {
        const start = (this.currentPage - 1) * this.pageSize;
        this.historyData = this.fullHistory.slice(start, start + this.pageSize);
    }

    handleViewAll() {
        this.isExpanded = true;
        this.loadHistory();
    }

    handleCollapse() {
        this.isExpanded = false;
    }

    handleFilterChange(event) {
        const field = event.target.name;
        if (field === 'fromDate') this.filterFromDate = event.detail.value;
        if (field === 'toDate') this.filterToDate = event.detail.value;
        if (field === 'status') this.filterStatus = event.detail.value;
    }

    applyFilters() {
        this.currentPage = 1;
        this.loadHistory();
    }

    // --- Report Generation ---

    toggleReportPanel() {
        this.isReportPanelOpen = !this.isReportPanelOpen;
    }

    handleReportFilterChange(event) {
        const field = event.target.name;
        if (field === 'reportFromDate') this.reportFromDate = event.detail.value;
        if (field === 'reportToDate') this.reportToDate = event.detail.value;
        if (field === 'reportResult') this.reportResult = event.detail.value;
    }

    handleGenerateAndDownload() {
        // Validations
        if (!this.reportFromDate || !this.reportToDate) {
            this.showToast('Error', 'Please select both start and end dates.', 'error');
            return;
        }

        const start = new Date(this.reportFromDate);
        const end = new Date(this.reportToDate);
        const maxDays = this.maxRangeMonths * 30; // approx

        // Calculate difference in days
        const diffTime = Math.abs(end - start);
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

        if (start > end) {
            this.showToast('Error', 'Start date must be before end date.', 'error');
            return;
        }

        if (diffDays > maxDays) {
            this.showToast('Error', `The duration between the start date and the end date cannot exceed ${this.maxRangeMonths} Months`, 'error');
            return;
        }

        this.isLoading = true;
        const startAgo = Math.max(0, this.daysAgoFromToday(this.reportToDate));
        const fromAgo = Math.max(startAgo, this.daysAgoFromToday(this.reportFromDate));
        const totalDays = Math.max(1, fromAgo - startAgo + 1);
        Promise.all([
            this.fetchChunks(startAgo, totalDays),
            getCustomerExportInfo({ customerId: this.recordId })
        ])
            .then(([items, info]) => {
                this.customerName = info && info.name ? info.name : '';
                this.customerCif = info && info.cif ? info.cif : '';
                let data = items;
                if (this.reportResult !== 'All') {
                    data = data.filter(item => item.result === this.reportResult);
                }
                this.exportToCsv(data);
                this.isReportPanelOpen = false;
            })
            .catch(error => {
                this.showToast('Error', 'Failed to generate report: ' + this.reduceErrors(error), 'error');
            })
            .finally(() => {
                this.isLoading = false;
            });
    }

    exportToCsv(data) {
        if (!data || data.length === 0) {
            this.showToast('Info', 'No data found to export', 'info');
            return;
        }

        let rowEnd = '\n';
        let csvString = '';

        // Header
        csvString += `Customer Name, CIF, From Date, To Date${rowEnd}`;
        csvString += `"${this.customerName || 'Customer'}", ${this.customerCif || ''}, ${this.reportFromDate}, ${this.reportToDate}${rowEnd}${rowEnd}`;

        let fields = ['Timestamp', 'Result', 'Device ID', 'IP Address', 'Location', 'Description', 'Error Code'];
        csvString += fields.join(',') + rowEnd;

        data.forEach(item => {
            csvString += (item.timestamp || '') + ',';
            csvString += (item.result || '') + ',';
            csvString += (item.channel || '') + ',';
            csvString += (item.category || '') + ',';
            csvString += '"' + (item.unit || '') + '",';
            csvString += '"' + (item.description || '') + '",';
            csvString += (item.errorCode || '');
            csvString += rowEnd;
        });

        // Download
        let downloadElement = document.createElement('a');
        downloadElement.href = 'data:text/csv;charset=utf-8,' + encodeURI(csvString);
        downloadElement.target = '_self';
        downloadElement.download = 'LoginActivityDetailsReport.csv';
        document.body.appendChild(downloadElement);
        downloadElement.click();
        document.body.removeChild(downloadElement);
    }

    // --- Pagination Actions ---

    handlePrevPage() {
        if (this.currentPage > 1) {
            this.currentPage--;
            this.applyHistoryPage();
        }
    }

    handleNextPage() {
        if (this.currentPage < this.totalPages) {
            this.currentPage++;
            this.applyHistoryPage();
        }
    }

    handlePageClick(event) {
        const page = event.target.dataset.value;
        if (page && page !== 'dots' && parseInt(page, 10) !== this.currentPage) {
            this.currentPage = parseInt(page, 10);
            this.applyHistoryPage();
        }
    }

    showToast(title, message, variant) {
        this.dispatchEvent(
            new ShowToastEvent({
                title: title,
                message: message,
                variant: variant
            })
        );
    }

    reduceErrors(errors) {
        if (!errors) return 'Unknown error';
        if (Array.isArray(errors)) return errors[0].message || errors[0];
        if (typeof errors === 'object') return errors.body?.message || errors.message || 'Unknown error';
        return errors;
    }
}