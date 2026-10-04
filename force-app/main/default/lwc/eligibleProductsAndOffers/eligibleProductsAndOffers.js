import { LightningElement, api, track } from 'lwc';
import createCases from '@salesforce/apex/EligibleProductsAndOffersController.createCases';
import updateProductDecisions from '@salesforce/apex/EligibleProductsAndOffersController.updateProductDecisions';
import getNBOData from '@salesforce/apex/EligibleProductsAndOffersController.getNBOData';

export default class EligibleProductsAndOffers extends LightningElement {
    @api recordId;
    @track isShowModal = true;
    @track isApplyDisabled = true;
    @track isLoading = true;
    @track isProcessing = false;
    @track loadingMessage = 'Loading eligible products and offers...';
    @track showSummary = false;
    
    @track yesCount = 0;
    @track noCount = 0;
    @track products = [];
    @track offers = [];

    get activeProducts() {
        return this.products.filter(p => !p.isActioned);
    }

    get activeOffers() {
        return this.offers.filter(o => !o.isActioned);
    }

    get hasNoProducts() {
        return this.activeProducts.length === 0;
    }

    get hasNoOffers() {
        return this.activeOffers.length === 0;
    }

    get productCountDisplay() {
        const count = this.activeProducts.length;
        return count + ' ' + (count === 1 ? 'Product' : 'Products');
    }

    get offerCountDisplay() {
        const count = this.activeOffers.length;
        return count + ' ' + (count === 1 ? 'Offer' : 'Offers');
    }

    get hasYesSelections() {
        return this.yesCount > 0;
    }

    get hasNoSelections() {
        return this.noCount > 0;
    }

    get hasAnySelections() {
        return this.hasYesSelections || this.hasNoSelections;
    }

    @api
    openModal() {
        this.isShowModal = true;
        this.isLoading = true;
        this.isProcessing = false;
        this.showSummary = false;
        this.yesCount = 0;
        this.noCount = 0;
        this.resetSelections();
        this.fetchNBOData();
    }

    @api
    closeModal() {
        this.hideModalBox();
    }

    hideModalBox() {  
        if (this.isProcessing) return;
        this.isShowModal = false;
        const closeEvent = new CustomEvent('modalclosed', {
            detail: { isClosed: true }
        });
        this.dispatchEvent(closeEvent);
    }

    fetchNBOData() {
        this.isLoading = true;
        this.loadingMessage = 'Fetching eligible products and offers...';
        if (!this.recordId) {
            this.isLoading = false;
            this.showToast('Error', 'Account ID is missing. Please refresh and try again.', 'error');
            return;
        }
        getNBOData({ accountId: this.recordId })
            .then(result => {
                this.isLoading = false;
                if (result && result.products) {
                    this.products = result.products.map((p, index) => ({
                        id: p.id,
                        name: p.name,
                        customerInterest: null,
                        isActioned: false,
                        radioName: 'product-' + (index + 1),
                        yesId: 'product-' + (index + 1) + '-yes',
                        noId: 'product-' + (index + 1) + '-no'
                    }));
                }
                if (result && result.offers) {
                    this.offers = result.offers.map((o, index) => ({
                        id: o.id,
                        name: o.name,
                        customerInterest: null,
                        isActioned: false,
                        radioName: 'offer-' + (index + 1),
                        yesId: 'offer-' + (index + 1) + '-yes',
                        noId: 'offer-' + (index + 1) + '-no'
                    }));
                }
                this.updateApplyButton();
                const totalItems = this.activeProducts.length + this.activeOffers.length;
                this.showToast(
                    'Data Loaded', 
                    'Found ' + totalItems + ' eligible items (' + this.activeProducts.length + ' products, ' + this.activeOffers.length + ' offers)', 
                    'success'
                );
            })
            .catch(error => {
                this.isLoading = false;
                console.error('Error fetching NBO data:', error);
                this.showToast('Error', 'Failed to load eligible products and offers: ' + (error.body ? error.body.message : error.message), 'error');
            });
    }

    resetSelections() {
        this.products = this.products.map(p => ({
            ...p,
            customerInterest: null,
            isActioned: false
        }));
        this.offers = this.offers.map(o => ({
            ...o,
            customerInterest: null,
            isActioned: false
        }));
        this.isApplyDisabled = true;
        this.yesCount = 0;
        this.noCount = 0;
    }

    handleRadioChange(event) {
        if (this.isProcessing) return;
        const itemId = event.target.dataset.id;
        const type = event.target.dataset.type;
        const value = event.target.value;
        if (type === 'product') {
            const productIndex = this.getProductIndex(itemId);
            if (productIndex >= 0 && !this.products[productIndex].isActioned) {
                const previousValue = this.products[productIndex].customerInterest;
                this.products[productIndex].customerInterest = value;
                this.updateCounts(previousValue, value);
            }
        } else if (type === 'offer') {
            const offerIndex = this.getOfferIndex(itemId);
            if (offerIndex >= 0 && !this.offers[offerIndex].isActioned) {
                const previousValue = this.offers[offerIndex].customerInterest;
                this.offers[offerIndex].customerInterest = value;
                this.updateCounts(previousValue, value);
            }
        }
        this.updateApplyButton();
        this.showSummary = this.hasAnySelections;
    }

    updateCounts(previousValue, newValue) {
        if (previousValue === 'yes') {
            this.yesCount = Math.max(0, this.yesCount - 1);
        } else if (previousValue === 'no') {
            this.noCount = Math.max(0, this.noCount - 1);
        }
        if (newValue === 'yes') {
            this.yesCount += 1;
        } else if (newValue === 'no') {
            this.noCount += 1;
        }
    }

    getProductIndex(itemId) {
        return this.products.findIndex(p => p.id === itemId && !p.isActioned);
    }

    getOfferIndex(itemId) {
        return this.offers.findIndex(o => o.id === itemId && !o.isActioned);
    }

    updateApplyButton() {
        const hasSelection = this.products.some(p => p.customerInterest && !p.isActioned) || 
                           this.offers.some(o => o.customerInterest && !o.isActioned);
        this.isApplyDisabled = !hasSelection;
    }

    async handleApply() {
        if (this.isProcessing) return;
        
        const selectedYesProducts = this.products.filter(p => p.customerInterest === 'yes' && !p.isActioned);
        const selectedNoProducts = this.products.filter(p => p.customerInterest === 'no' && !p.isActioned);
        const selectedYesOffers = this.offers.filter(o => o.customerInterest === 'yes' && !o.isActioned);
        const selectedNoOffers = this.offers.filter(o => o.customerInterest === 'no' && !o.isActioned);
        
        if (!this.hasAnySelections) {
            this.showToast('No Selection', 'Please select Yes or No for at least one product or offer', 'warning');
            return;
        }

        this.isProcessing = true;
        this.isApplyDisabled = true;
        let allSuccess = true;
        let successMessages = [];
        let errorMessages = [];
        
        try {
            // Process "No" Products
            if (selectedNoProducts.length > 0) {
                const result = await this.handleItemUpdate(selectedNoProducts, 'Product');
                if (result.success) {
                    successMessages.push(result.message);
                    this.markItemsAsActioned(selectedNoProducts);
                } else {
                    allSuccess = false;
                    errorMessages.push(result.message);
                }
            }
            // Process "Yes" Products
            if (selectedYesProducts.length > 0) {
                const updateResult = await this.handleItemUpdate(selectedYesProducts, 'Product');
                if (updateResult.success) {
                    const caseResult = await this.handleCaseCreation(selectedYesProducts, []);
                    if (caseResult.success) {
                        successMessages.push(caseResult.message);
                        this.markItemsAsActioned(selectedYesProducts);
                    } else {
                        allSuccess = false;
                        errorMessages.push(caseResult.message);
                    }
                } else {
                    allSuccess = false;
                    errorMessages.push(updateResult.message);
                }
            }
            // Process "No" Offers
            if (selectedNoOffers.length > 0) {
                const result = await this.handleItemUpdate(selectedNoOffers, 'Offer');
                if (result.success) {
                    successMessages.push(result.message);
                    this.markItemsAsActioned(selectedNoOffers);
                } else {
                    allSuccess = false;
                    errorMessages.push(result.message);
                }
            }
            // Process "Yes" Offers
            if (selectedYesOffers.length > 0) {
                const updateResult = await this.handleItemUpdate(selectedYesOffers, 'Offer');
                if (updateResult.success) {
                    const caseResult = await this.handleCaseCreation([], selectedYesOffers);
                    if (caseResult.success) {
                        successMessages.push(caseResult.message);
                        this.markItemsAsActioned(selectedYesOffers);
                    } else {
                        allSuccess = false;
                        errorMessages.push(caseResult.message);
                    }
                } else {
                    allSuccess = false;
                    errorMessages.push(updateResult.message);
                }
            }
            
            // --- FIX STARTS HERE ---
            // After processing, check if any active items remain.
            // If none, we consider the process "complete" and close the modal after showing a toast.
            const remainingItems = this.activeProducts.length + this.activeOffers.length;
            
            if (remainingItems === 0) {
                // All items have been actioned – show success (or combined messages) and close
                this.isProcessing = false; // ensure spinner stops
                this.updateApplyButton();
                this.showSummary = false;
                
                let finalMessage = 'All items processed successfully.';
                if (successMessages.length > 0) {
                    finalMessage = successMessages.join(' | ');
                }
                this.showToast('Success', finalMessage, 'success');
                
                // Close modal after a short delay so the toast is visible
                setTimeout(() => {
                    this.hideModalBox();
                }, 2000);
            } else {
                // There are still items left – show info and keep modal open
                this.isProcessing = false;
                this.updateApplyButton();
                this.showSummary = false; // reset summary for new selections
                this.showToast('Remaining Items', remainingItems + ' items still pending for review', 'info');
            }
            // --- FIX ENDS HERE ---
            
        } catch (error) {
            console.error('Error in handleApply:', error);
            this.showToast('Error', 'An unexpected error occurred. Please try again.', 'error');
            this.isProcessing = false;
            this.updateApplyButton();
        }
    }

    handleItemUpdate(items, itemType) {
        return new Promise((resolve) => {
            if (!items || items.length === 0) {
                resolve({ success: true, message: 'No ' + itemType + 's to update' });
                return;
            }
            const selectedItems = items.map(item => ({
                id: item.id,
                name: item.name,
                itemType: itemType,
                customerInterest: item.customerInterest
            }));
            updateProductDecisions({ accountId: this.recordId, selectedItems: selectedItems })
                .then(result => {
                    resolve(result);
                })
                .catch(error => {
                    resolve({
                        success: false,
                        message: 'Failed to update ' + itemType + 's: ' + (error.body ? error.body.message : error.message)
                    });
                });
        });
    }

    handleCaseCreation(yesProducts, yesOffers) {
        return new Promise((resolve) => {
            const selectedItems = [];
            yesProducts.forEach(p => {
                selectedItems.push({
                    id: p.id,
                    name: p.name,
                    itemType: 'Product',
                    customerInterest: 'yes'
                });
            });
            yesOffers.forEach(o => {
                selectedItems.push({
                    id: o.id,
                    name: o.name,
                    itemType: 'Offer',
                    customerInterest: 'yes'
                });
            });
            if (selectedItems.length === 0) {
                resolve({ success: true, message: 'No items to create cases for' });
                return;
            }
            createCases({ accountId: this.recordId, selectedItems: selectedItems })
                .then(result => {
                    if (result.success) {
                        const caseEvent = new CustomEvent('casescreated', {
                            detail: {
                                products: yesProducts,
                                offers: yesOffers,
                                accountId: this.recordId,
                                totalCases: result.caseCount || selectedItems.length,
                                cases: result.cases || [],
                                timestamp: new Date().toISOString()
                            }
                        });
                        this.dispatchEvent(caseEvent);
                    }
                    resolve(result);
                })
                .catch(error => {
                    resolve({
                        success: false,
                        message: 'Failed to create cases: ' + (error.body ? error.body.message : error.message)
                    });
                });
        });
    }

    markItemsAsActioned(items) {
        if (!items || items.length === 0) return;
        items.forEach(item => {
            const productIndex = this.products.findIndex(p => p.id === item.id && !p.isActioned);
            if (productIndex >= 0) {
                this.products[productIndex].isActioned = true;
                this.products[productIndex].customerInterest = null;
            }
            const offerIndex = this.offers.findIndex(o => o.id === item.id && !o.isActioned);
            if (offerIndex >= 0) {
                this.offers[offerIndex].isActioned = true;
                this.offers[offerIndex].customerInterest = null;
            }
        });
        this.products = [...this.products];
        this.offers = [...this.offers];
    }

    refreshList() {
        this.products = this.products.filter(p => !p.isActioned);
        this.offers = this.offers.filter(o => !o.isActioned);
        this.yesCount = 0;
        this.noCount = 0;
        this.isProcessing = false;
        this.showSummary = false;
        this.updateApplyButton();
    }

    showToast(title, message, variant) {
        const toastEvent = new CustomEvent('showtoast', {
            detail: { 
                title, 
                message, 
                variant,
                duration: variant === 'error' ? 5000 : 3000
            }
        });
        this.dispatchEvent(toastEvent);
    }
}