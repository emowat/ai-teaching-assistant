/** Demo starter file for the student Monaco editor. */
export const LINKED_LIST_CPP = `#include <iostream>
using namespace std;

struct Node {
    int data;
    Node* next;
    Node(int v) : data(v), next(nullptr) {}
};

class LinkedList {
private:
    Node* head;

public:
    LinkedList() {}  // BUG: head never initialized

    void insert(int val) {
        Node* newNode = new Node(val);
        newNode->next = head->next;  // SEGFAULT HERE
        head = newNode;
    }

    void print() {
        Node* curr = head;
        while (curr != nullptr) {
            cout << curr->data << " -> ";
            curr = curr->next;
        }
        cout << "NULL" << endl;
    }
};

int main() {
    LinkedList list;
    list.insert(1);  // crashes here
    list.insert(2);
    list.print();
    return 0;
}
`;
